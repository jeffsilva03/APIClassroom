import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from classroom_app.activities import Activities, deadline
from classroom_app.config import GOOGLE_SCOPES, Settings
from classroom_app.errors import ServiceError
from classroom_app.google import GoogleClient, google_error, budget
from classroom_app.google_authorization import ACTIVITY_SCOPE, BASE_SCOPES, validate_credentials
from classroom_app.materials import Materials

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
COURSE = {"id": "1", "nome": "Nuvem", "status": "ACTIVE"}
TASK = {"id": "a", "courseId": "1", "state": "PUBLISHED", "title": "Tarefa", "description": "Descrição completa", "workType": "ASSIGNMENT", "maxPoints": 0, "dueDate": {"year": 2026, "month": 10, "day": 22}, "dueTime": {"hours": 1}}


@pytest.fixture(autouse=True)
def clean_budget():
    marker = budget.set(None)
    yield
    budget.reset(marker)


@pytest.fixture
def service():
    google, courses = AsyncMock(), AsyncMock()
    courses.detail.return_value = COURSE
    courses.all.return_value = [COURSE]
    return Activities(google, courses, lambda: NOW)


@pytest.mark.parametrize("raw,local,state", [
    ({}, None, "sem_prazo"),
    ({"dueDate": {"year": 2026, "month": 10, "day": 22}}, None, "incompleto"),
    ({"dueDate": {"year": 2026, "month": 10, "day": 22}, "dueTime": {}}, "2026-10-21T21:00:00-03:00", "futuro"),
    ({"dueDate": {"year": 2026, "month": 10, "day": 21}, "dueTime": {"hours": 1}}, "2026-10-20T22:00:00-03:00", "vencido"),
    ({"dueDate": {"year": 2026, "month": 10, "day": 21}, "dueTime": {"hours": 15, "minutes": 30}}, "2026-10-21T12:30:00-03:00", "futuro"),
    ({"dueDate": {"year": 2018, "month": 12, "day": 1}, "dueTime": {"hours": 3}}, "2018-12-01T01:00:00-02:00", "vencido"),
    ({"dueDate": {"year": 2026, "month": 2, "day": 30}, "dueTime": {}}, None, "incompleto"),
    ({"dueTime": {}}, None, "incompleto"),
])
def test_deadlines_keep_utc_and_do_not_invent_missing_time(raw, local, state):
    result = deadline(raw, NOW)
    assert result["em_sao_paulo"] == local
    assert result["situacao_temporal"] == state
    assert result["data_utc_original"] == raw.get("dueDate")
    assert result["hora_utc_original"] == raw.get("dueTime")


async def test_list_deduplicates_published_and_preserves_fields(service):
    service.google.get.return_value = {"courseWork": [TASK, TASK, TASK | {"id": "draft", "state": "DRAFT"}], "nextPageToken": "next"}
    result = await service.list("1", 2, order="prazo")
    assert len(result["itens"]) == 1
    item = result["itens"][0]
    assert item["tipo"] == "ASSIGNMENT" and item["pontuacao_maxima"] == 0
    assert item["publicado_em"] is None and item["estado_publicacao"] == "PUBLISHED"
    assert item["prazo"]["em_sao_paulo"].startswith("2026-10-21")
    assert result["proxima_pagina"] == "next"
    assert service.google.get.call_args.args[1] == {"pageSize": 2, "courseWorkStates": "PUBLISHED", "orderBy": "dueDate asc,updateTime desc"}
    service.google.scopes.assert_not_called()


async def test_empty_course_and_missing_fields(service):
    service.google.get.return_value = {}
    assert (await service.list("1"))["itens"] == []
    service.google.get.return_value = {"courseWork": [{"id": "a", "state": "PUBLISHED"}]}
    result = (await service.list("1"))["itens"][0]
    assert result["descricao"] is None and result["pontuacao_maxima"] is None
    assert result["prazo"]["em_sao_paulo"] is None


@pytest.mark.parametrize("size,token", [(0, None), (51, None), (1, ""), (1, " "), (1, "a\nb"), (1, "x" * 2049)])
async def test_invalid_pagination_before_google(service, size, token):
    with pytest.raises(ServiceError):
        await service.list("1", size, token)
    service.google.get.assert_not_called()


async def test_permission_is_the_endpoint_decision(service):
    service.google.get.side_effect = ServiceError("escopo_google_insuficiente", "Acesso recusado", 403)
    with pytest.raises(ServiceError) as exc:
        await service.list("1")
    assert exc.value.status == 403
    service.google.scopes.assert_not_called()


async def test_full_description_and_detail_binding(service):
    service.google.get.return_value = TASK | {"description": "x" * 10000}
    assert len((await service.detail("1", "a"))["atividade"]["descricao"]) == 10000
    for changed in ({"courseId": "other"}, {"state": "DRAFT"}, {"id": "other"}):
        service.google.get.return_value = TASK | changed
        with pytest.raises(ServiceError) as exc:
            await service.detail("1", "a")
        assert exc.value.status == 404


@pytest.mark.parametrize("course,activity", [("../1", "a"), ("1", "../a")])
async def test_invalid_identifiers(service, course, activity):
    with pytest.raises(ServiceError):
        await service.detail(course, activity)
    service.google.get.assert_not_called()


async def test_archived_requires_explicit_permission(service):
    service.courses.detail.side_effect = ServiceError("disciplina_indisponivel", "Arquivada", 404)
    with pytest.raises(ServiceError):
        await service.list("1")
    service.google.get.assert_not_called()
    service.courses.detail.side_effect = None
    service.google.get.return_value = {}
    await service.list("1", archived=True)
    service.courses.detail.assert_awaited_with("1", True)


async def test_submissions_are_always_own_and_status_not_guessed(service):
    service.google.get.return_value = {"studentSubmissions": [
        {"id": "s", "courseId": "1", "courseWorkId": "a", "userId": "private-student", "state": "NEW"},
        {"id": "s2", "courseId": "1", "courseWorkId": "a", "state": "RETURNED", "assignedGrade": 0, "late": False},
    ]}
    result = await service.submissions("1", "a")
    assert service.google.get.call_args.args == ("courses/1/courseWork/a/studentSubmissions", {"userId": "me", "pageSize": 50})
    assert result["entregas"][0]["atrasada_segundo_google"] is None
    assert result["entregas"][1]["nota_atribuida"] == 0
    assert not result["entregas"][1]["atrasada_segundo_google"]
    assert "private-student" not in json.dumps(result)


async def test_search_checks_full_description_and_has_continuation(service):
    service.google.get.return_value = {"courseWork": [TASK | {"description": "x" * 3000 + " Docker"}], "nextPageToken": "next"}
    result = await service.search("docker")
    assert len(result["resultados"]) == 1 and result["resultados"][0]["descricao_truncada"]
    assert result["continuacao"]
    service.google.get.assert_awaited_once()


async def test_search_empty_page_is_not_global_absence(service):
    service.google.get.return_value = {"courseWork": [TASK], "nextPageToken": "next"}
    result = await service.search("nao encontrado")
    assert not result["resultados"] and result["continuacao"]


async def test_search_pagination_deduplicates_and_detects_cycle(service):
    service.google.get.side_effect = [
        {"courseWork": [TASK], "nextPageToken": "A"},
        {"courseWork": [TASK, TASK | {"id": "b"}], "nextPageToken": "B"},
        {"courseWork": [], "nextPageToken": "A"},
    ]
    first = await service.search()
    second = await service.search(cursor=first["continuacao"])
    assert [i["id"] for i in second["resultados"]] == ["b"]
    with pytest.raises(ServiceError, match="repetiu"):
        await service.search(cursor=second["continuacao"])


async def test_search_deduplicates_shared_courses(service):
    service.courses.all.return_value = [COURSE, COURSE]
    service.google.get.return_value = {"courseWork": [TASK]}
    result = await service.search()
    assert len(result["resultados"]) == 1 and result["continuacao"] is None
    service.courses.all.assert_awaited_with(False)


@pytest.mark.parametrize("kwargs", [{"start": "2026-10-22", "end": "2026-10-21"}, {"start": "ontem"}, {"created_since": "2026-10-21T10:00:00"}, {"order": "creationTime"}, {"due": "pendentes"}, {"query": " "}, {"cursor": "not-json"}])
async def test_invalid_search_filters(service, kwargs):
    with pytest.raises(ServiceError):
        await service.search(**kwargs)
    service.google.get.assert_not_called()


async def test_cursor_is_bound_to_original_filters(service):
    service.google.get.return_value = {"nextPageToken": "next"}
    first = await service.search("docker")
    with pytest.raises(ServiceError) as error:
        await service.search("outro", cursor=first["continuacao"])
    assert error.value.code == "cursor_invalido"


@pytest.mark.parametrize("due,start,end,count", [("futuro", "2026-10-21", "2026-10-21", 1), ("sem_prazo", None, None, 1), ("vencido", None, None, 0), ("com_prazo", "2026-10-22", None, 0)])
async def test_deadline_filters_use_local_dates(service, due, start, end, count):
    service.google.get.return_value = {"courseWork": [TASK, {"id": "none", "state": "PUBLISHED"}]}
    result = await service.search(due=due, start=start, end=end)
    assert len(result["resultados"]) == count


async def test_activity_pdf_binding_is_checked_after_materials(service):
    materials = Materials(service.google, service.courses, service)
    task = TASK | {"materials": [{"driveFile": {"driveFile": {"id": "pdf", "title": "anexo.pdf"}}}]}
    service.google.get.side_effect = [{}, {"courseWork": [task]}]
    course, attachment, item = await materials.linked_file("1", "pdf")
    assert attachment["id"] == "pdf" and item["id"] == "a" and course["id"] == "1"


@pytest.mark.parametrize("reason,expected", [("ACCESS_TOKEN_SCOPE_INSUFFICIENT", "escopo_google_insuficiente"), ("ADMIN_POLICY_ENFORCED", "politica_institucional"), ("SERVICE_DISABLED", "api_google_desabilitada"), ("unknown", "google_sem_permissao")])
def test_google_errors_are_specific_only_with_evidence(reason, expected):
    error = google_error(403, {"error": {"message": "private-sentinel", "details": [{"reason": reason}]}})
    assert error.code == expected and "private-sentinel" not in json.dumps(error.payload())


def auth_client(scopes=None, fail=None, account="student@example.com"):
    def handler(request):
        path = request.url.path
        if path == "/token":
            return httpx.Response(400 if fail == "refresh" else 200, json={"access_token": "private-token-sentinel", "scope": " ".join(scopes if scopes is not None else GOOGLE_SCOPES)})
        if path == "/drive/v3/about":
            return httpx.Response(200, json={"user": {"emailAddress": account}})
        if path == "/v1/courses":
            return httpx.Response(200, json={"courses": [{"id": "1", "courseState": "ACTIVE"}]})
        return httpx.Response(403 if fail and fail in path else 200, json={})
    return httpx.Client(transport=httpx.MockTransport(handler))


AUTH = {"client_id": "fixture-client", "client_secret": "private-client-sentinel", "refresh_token": "private-refresh-sentinel", "token_uri": "https://oauth2.googleapis.com/token", "scopes": GOOGLE_SCOPES}


def test_authorization_uses_actual_scopes_and_all_endpoints():
    with auth_client() as client:
        data, report = validate_credentials(AUTH, "student@example.com", "1", client)
    assert set(data["scopes"]) == set(GOOGLE_SCOPES)
    assert set(report["probes"]) == {"drive", "courses", "materials", "announcements", "activities", "own_submissions"}
    assert all(v["http"] == 200 for v in report["probes"].values())
    assert "private-" not in json.dumps(report)


@pytest.mark.parametrize("scopes,fail,account,code", [(list(BASE_SCOPES), None, "student@example.com", "autorizacao_incompleta"), (None, "refresh", "student@example.com", "google_reautorizar"), (None, "courseWork", "student@example.com", "validacao_google_recusada"), (None, None, "other@example.com", "conta_google_incorreta"), (GOOGLE_SCOPES + ["https://www.googleapis.com/auth/classroom.rosters"], None, "student@example.com", "escopos_inesperados")])
def test_incomplete_credentials_never_validate(scopes, fail, account, code):
    with auth_client(scopes, fail, account) as client, pytest.raises(ServiceError) as error:
        validate_credentials(AUTH, "student@example.com", "1", client)
    assert error.value.code == code


async def test_refresh_reports_granted_scopes_not_stored_json(monkeypatch):
    calls = []
    def request(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status=200, data=json.dumps({"access_token": "refreshed-token", "expires_in": 3600, "scope": " ".join(BASE_SCOPES)}).encode(), headers={})
    monkeypatch.setattr("classroom_app.google.BoundedRequest", lambda: request)
    google = GoogleClient(Settings(classroom_credentials=json.dumps(AUTH)))
    assert google.scopes() == []
    assert await google.token("classroom") == "refreshed-token"
    assert set(google.scopes()) == BASE_SCOPES and ACTIVITY_SCOPE not in google.scopes()
    await google.token("classroom")
    assert len(calls) == 1
    google.credentials["classroom"].expiry = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    await google.token("classroom")
    assert len(calls) == 2


def test_oauthlib_alias_warning_and_canonical_request(monkeypatch):
    from oauthlib.oauth2.rfc6749.parameters import parse_token_response
    monkeypatch.delenv("OAUTHLIB_RELAX_TOKEN_SCOPE", raising=False)
    response = json.dumps({"access_token": "fixture-only", "token_type": "Bearer", "scope": " ".join(GOOGLE_SCOPES)})
    requested = [s.replace("classroom.student-submissions.me.readonly", "classroom.coursework.me.readonly") for s in GOOGLE_SCOPES]
    with pytest.raises(Warning) as changed:
        parse_token_response(response, scope=requested)
    assert ACTIVITY_SCOPE in changed.value.new_scope
    assert parse_token_response(response, scope=GOOGLE_SCOPES)["access_token"] == "fixture-only"


def test_failed_validation_preserves_saved_credential_and_never_publishes(tmp_path, monkeypatch):
    from scripts import authorize_google
    local = tmp_path / ".local"
    local.mkdir()
    source = local / "candidate.json"
    source.write_text(json.dumps(AUTH))
    previous = local / "google-authorized-activities.json"
    previous.write_text("previous-functional-credential")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["authorize_google", "--reuse", str(source), "--expected-email", "student@example.com", "--publish"])
    def invalid(*args):
        raise ServiceError("autorizacao_incompleta", "Permissão ausente", 422)
    monkeypatch.setattr(authorize_google, "validate_credentials", invalid)
    publish = []
    monkeypatch.setattr(authorize_google.subprocess, "run", lambda *args, **kwargs: publish.append(args))
    with pytest.raises(SystemExit):
        authorize_google.main()
    assert previous.read_text() == "previous-functional-credential" and not publish


async def test_revoked_refresh_token_is_sanitized(monkeypatch):
    def request(**kwargs):
        return SimpleNamespace(status=400, data=b'{"error":"invalid_grant","error_description":"private-sentinel"}', headers={})
    monkeypatch.setattr("classroom_app.google.BoundedRequest", lambda: request)
    google = GoogleClient(Settings(classroom_credentials=json.dumps(AUTH)))
    with pytest.raises(ServiceError) as error:
        await google.token("classroom")
    assert error.value.code == "google_reautorizar" and "private-sentinel" not in json.dumps(error.value.payload())
