import io
import json
import time
from unittest.mock import AsyncMock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from classroom_app.app import create_app
from classroom_app.config import Settings
from classroom_app.courses import Courses
from classroom_app.documents import Documents
from classroom_app.errors import ServiceError
from classroom_app.google import GoogleClient, budget, google_error
from classroom_app.materials import Materials, attachments
from classroom_app.pdf_worker import extract
from classroom_app.security import TokenVerifier


@pytest.fixture(autouse=True)
def reset_budget():
    marker = budget.set(None)
    yield
    budget.reset(marker)


@pytest.fixture
def settings():
    return Settings(public_url="http://testserver", issuer="https://issuer.example/", owner_sub="owner")


@pytest.fixture
def google():
    return AsyncMock()


@pytest.mark.parametrize("archived,expected", [(False, ["1", "course-demo"]), (True, ["1", "2", "course-demo"])])
async def test_active_filter_pagination_dedup(settings, google, archived, expected):
    google.get.side_effect = [
        {"courses": [{"id": "1", "name": "Nuvem", "courseState": "ACTIVE"}, {"id": "2", "name": "Antiga", "courseState": "ARCHIVED"}], "nextPageToken": "next"},
        {"courses": [{"id": "course-demo", "name": "Projeto Integrador - Turma Exemplo", "courseState": "ACTIVE"}, {"id": "1", "name": "Nuvem", "courseState": "ACTIVE"}]},
    ]
    result = await Courses(google, settings).all(archived)
    assert [i["id"] for i in result] == expected
    assert google.get.call_args_list[1].args[1]["pageToken"] == "next"
    assert google.get.call_args_list[0].args[1]["courseStates"] == (["ACTIVE", "ARCHIVED"] if archived else "ACTIVE")


@pytest.mark.parametrize("query", ["automacao", "AUTOMAÇÃO", "Projeto Integrador", "Extensao", "Turma Exemplo"])
async def test_shared_aliases(settings, google, query):
    google.get.return_value = {"courses": [{"id": "course-demo", "name": "Projeto Integrador - Turma Exemplo", "courseState": "ACTIVE"}]}
    result = await Courses(google, settings).search(query)
    assert len(result["disciplinas"]) == 1
    assert not result["ambigua"]


async def test_ambiguity(settings, google):
    google.get.return_value = {"courses": [{"id": str(n), "name": f"Backend {n}", "courseState": "ACTIVE"} for n in (1, 2)]}
    assert (await Courses(google, settings).search("back"))["ambigua"]


def test_attachment_types_and_missing_data():
    assert attachments({}) == []
    assert len(attachments({"materials": [{"link": {"url": "https://example.com"}}, {"driveFile": {"driveFile": {"id": "abc", "title": "notes.pdf"}}}, {"youtubeVideo": {"id": "x"}}, {"form": {"formUrl": "https://example.com"}}]})) == 4


async def test_file_binding_checks_all_pages(settings, google):
    courses = AsyncMock()
    courses.detail.return_value = {"id": "1"}
    m = Materials(google, courses)
    google.get.side_effect = [{"nextPageToken": "next"}, {"courseWorkMaterial": [{"id": "m", "materials": [{"driveFile": {"driveFile": {"id": "file"}}}]}]}]
    course, linked, material = await m.linked_file("1", "file")
    assert linked["id"] == "file"
    assert google.get.call_args_list[1].args[1]["pageToken"] == "next"


async def test_arbitrary_drive_id_rejected_before_download(settings, google):
    courses = AsyncMock()
    google.get.return_value = {}
    documents = Documents(google, Materials(google, courses), settings)
    with pytest.raises(ServiceError, match="Arquivo não encontrado"):
        await documents.read("1", "arbitrary")
    google.download.assert_not_called()


@pytest.mark.parametrize("mime,size,can_download,code", [("image/png", 10, True, "tipo_invalido"), ("application/pdf", 30 * 1024 * 1024, True, "pdf_grande"), ("application/pdf", 10, False, "download_proibido")])
async def test_pdf_preflight(settings, google, mime, size, can_download, code):
    materials = AsyncMock()
    materials.linked_file.return_value = ({}, {}, {})
    google.get.return_value = {"mimeType": mime, "size": str(size), "capabilities": {"canDownload": can_download}}
    with pytest.raises(ServiceError) as err:
        await Documents(google, materials, settings).read("1", "file")
    assert err.value.code == code
    google.download.assert_not_called()


async def test_pdf_page_limit(settings, google):
    with pytest.raises(ServiceError) as err:
        await Documents(google, AsyncMock(), settings).read("1", "file", 1, 6)
    assert err.value.code == "paginas_invalidas"


def test_blank_scanned_and_out_of_range():
    writer = PdfWriter()
    for _ in range(7):
        writer.add_blank_page(width=100, height=100)
    stream = io.BytesIO()
    writer.write(stream)
    result = extract(stream.getvalue(), 1, 5, 0)
    assert result["total_paginas"] == 7
    assert result["continuacao"] == {"pagina_inicio": 6, "offset": 0}
    assert all(p["sem_texto_extraivel"] for p in result["paginas"])
    with pytest.raises(ValueError, match="pagina_inexistente"):
        extract(stream.getvalue(), 8, 9, 0)


@pytest.mark.parametrize("status,code", [(401, "google_reautorizar"), (403, "google_sem_permissao"), (404, "nao_encontrado"), (429, "quota_google"), (503, "google_indisponivel")])
def test_sanitized_google_errors(status, code):
    assert google_error(status).code == code


async def test_missing_credentials(settings):
    with pytest.raises(ServiceError) as err:
        await GoogleClient(settings).token("classroom")
    assert err.value.status == 503


def test_private_endpoints_require_auth(settings, google):
    with TestClient(create_app(settings, google)) as client:
        for path in ("/mcp", "/disciplinas", "/integracao", "/disciplinas/1/arquivos/file/texto"):
            r = client.post(path, json={}) if path == "/mcp" else client.get(path)
            assert r.status_code == 401
            assert "resource_metadata" in r.headers["www-authenticate"]
        assert client.get("/health").status_code == 200
        assert client.get("/.well-known/oauth-protected-resource").json()["resource"] == "http://testserver/mcp"
    google.get.assert_not_called()


@pytest.fixture
def signed(settings):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())) | {"kid": "test"}
    verifier = TokenVerifier(settings)
    verifier.keys = [jwk]
    verifier.cached_at = time.monotonic()
    def make(**updates):
        claims = {"sub": "owner", "aud": settings.resource, "iss": settings.issuer, "iat": int(time.time()), "exp": int(time.time()) + 300, "scope": "classroom:read"} | updates
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})
    return verifier, make


@pytest.mark.parametrize("updates,code", [({"exp": 1}, "token_invalido"), ({"sub": "other"}, "identidade_nao_autorizada"), ({"aud": "google-drive"}, "token_invalido"), ({"iss": "https://other/"}, "token_invalido"), ({"scope": ""}, "escopo_insuficiente")])
async def test_tokens(settings, signed, updates, code):
    verifier, make = signed
    with pytest.raises(ServiceError) as err:
        await verifier.verify(make(**updates))
    assert err.value.code == code


def test_rate_limit_and_origin(settings, google, signed):
    verifier, make = signed
    google.get.return_value = {}
    with TestClient(create_app(settings, google, verifier)) as client:
        headers = {"Authorization": "Bearer " + make()}
        assert client.get("/disciplinas", headers=headers | {"Origin": "https://evil.example"}).status_code == 403
        for _ in range(60):
            assert client.get("/disciplinas", headers=headers).status_code == 200
        assert client.get("/disciplinas", headers=headers).status_code == 429


def test_mcp_wire_initialization_schemas_and_tool(settings, google, signed):
    verifier, make = signed
    google.get.return_value = {"courses": [{"id": "1", "name": "Teste unitário", "courseState": "ACTIVE"}]}
    with TestClient(create_app(settings, google, verifier)) as client:
        headers = {"Authorization": "Bearer " + make(), "Accept": "application/json, text/event-stream"}
        def rpc(method, params):
            r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, headers=headers)
            assert r.status_code == 200, r.text
            return r.json()["result"]
        initialized = rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "tests", "version": "1"}})
        assert initialized["serverInfo"]["name"] == "APIClassroom"
        tools = rpc("tools/list", {})["tools"]
        assert len(tools) == 11
        assert all(t["annotations"]["readOnlyHint"] and t["inputSchema"]["type"] == "object" for t in tools)
        result = rpc("tools/call", {"name": "listar_disciplinas", "arguments": {}})
        assert result["structuredContent"]["disciplinas"][0]["id"] == "1"
