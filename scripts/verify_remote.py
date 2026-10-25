"""Execute com Python e requirements-dev.txt; exibe apenas resultados agregados."""
import argparse
import asyncio
import json
from pathlib import Path

import httpx
import httpx2
import jwt
from jsonschema import Draft202012Validator
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

EXPECTED_TOOLS = {"listar_disciplinas", "buscar_disciplina", "detalhar_disciplina", "listar_materiais", "buscar_materiais", "listar_arquivos", "ler_pdf", "pesquisar_documentos", "listar_avisos", "listar_atividades", "verificar_integracao", "detalhar_atividade", "buscar_atividades", "consultar_entregas", "inspecionar_anexo", "listar_conteudo_zip", "ler_arquivo_zip"}

async def verify_transport(base, token, origin):
    """Reproduz os cabeçalhos do cliente e observa a sequência do SDK oficial."""
    seen = []
    headers = {"Authorization": "Bearer " + token}
    if origin:
        headers["Origin"] = origin

    async def request_hook(request):
        if request.method == "POST":
            assert request.headers["authorization"] == headers["Authorization"]
            assert request.headers["content-type"].startswith("application/json")
            assert all(t in request.headers["accept"] for t in ("application/json", "text/event-stream"))

    async def response_hook(response):
        request = response.request
        if request.method == "POST":
            method = json.loads(request.content)["method"]
            assert response.status_code == (202 if method == "notifications/initialized" else 200)
            if response.status_code == 200:
                assert response.headers["content-type"].startswith("application/json")
            seen.append(method)

    async with httpx2.AsyncClient(headers=headers, timeout=60, event_hooks={"request": [request_hook], "response": [response_hook]}) as http:
        async with streamable_http_client(base + "/mcp", http_client=http) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=60) as session:
                init = await session.initialize()
                tools = await session.list_tools()
                assert init.server_info.name == "APIClassroom" and len(tools.tools) == len(EXPECTED_TOOLS)
                assert {tool.name for tool in tools.tools} == EXPECTED_TOOLS
                for tool in tools.tools:
                    Draft202012Validator.check_schema(tool.input_schema)
                    if tool.output_schema:
                        Draft202012Validator.check_schema(tool.output_schema)
                result = await session.call_tool("listar_disciplinas", {"tamanho": 1})
                assert not result.is_error and result.structured_content is not None
                schema = next(tool.output_schema for tool in tools.tools if tool.name == "listar_disciplinas")
                Draft202012Validator(schema).validate(result.structured_content)
    assert seen[:4] == ["initialize", "notifications/initialized", "tools/list", "tools/call"]
    print("SDK initialize > initialized >", len(EXPECTED_TOOLS), "ferramentas > chamada:", origin or "sem Origin", "OK")


async def verify(args):
    stored = json.loads(args.token_file.read_text())
    token = stored["access_token"]
    base = args.url.rstrip("/")
    async with httpx.AsyncClient(timeout=30) as client:
        assert (await client.get(base + "/health")).status_code == 200
        for endpoint in ("/disciplinas", "/mcp"):
            r = await client.get(base + endpoint)
            assert r.status_code == 401 and "resource_metadata" in r.headers["www-authenticate"]
            invalid = await client.get(base + endpoint, headers={"Authorization": "Bearer invalid"})
            assert invalid.status_code == 401
        metadata = (await client.get(base + "/.well-known/oauth-protected-resource")).json()
        assert metadata["resource"] == base + "/mcp"
        issuer = metadata["authorization_servers"][0]
        discovery = (await client.get(issuer.rstrip("/") + "/.well-known/oauth-authorization-server")).json()
        assert discovery["issuer"] == issuer and "S256" in discovery["code_challenge_methods_supported"]
        jwks = (await client.get(issuer.rstrip("/") + "/.well-known/jwks.json")).json()
        key = next(k for k in jwks["keys"] if k["kid"] == jwt.get_unverified_header(token)["kid"])
        claims = jwt.decode(token, jwt.PyJWK.from_dict(key).key, algorithms=["RS256"], audience=metadata["resource"], issuer=issuer, options={"require": ["exp", "iat", "iss", "aud", "sub"]})
        assert claims["sub"] == stored["sub"] and "classroom:read" in claims["scope"].split()
        for origin in ("https://chatgpt.com", "https://chat.openai.com"):
            assert (await client.post(base + "/mcp", headers={"Origin": origin}, json={})).status_code == 401
            assert (await client.post(base + "/mcp", headers={"Origin": origin, "Authorization": "Bearer invalid"}, json={})).status_code == 401
        for origin in ("https://evil.example", "https://chatgpt.com.evil.example", "null"):
            response = await client.post(base + "/mcp", headers={"Origin": origin, "Authorization": "Bearer " + token}, json={})
            assert response.status_code == 403 and response.json()["erro"]["codigo"] == "origem_nao_permitida"
    print("HTTPS, metadados e proteção anônima: OK")
    print("JWT assinado, issuer, audience/recurso, validade, proprietário e escopo: OK")
    for origin in (None, "https://chatgpt.com", "https://chat.openai.com"):
        await verify_transport(base, token, origin)
    async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + token}, timeout=60) as http:
        async with streamable_http_client(base + "/mcp", http_client=http) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=60) as session:
                init = await session.initialize()
                tools = await session.list_tools()
                print("MCP inicializado:", init.server_info.name, "ferramentas:", len(tools.tools))
                assert {tool.name for tool in tools.tools} == EXPECTED_TOOLS

                async def call(name, arguments):
                    result = await session.call_tool(name, arguments)
                    if result.is_error:
                        code = (result.structured_content or {}).get("erro", {}).get("codigo", "erro_mcp")
                        raise AssertionError(name + ": " + code)
                    assert result.structured_content is not None
                    schema = next(t.output_schema for t in tools.tools if t.name == name)
                    if schema:
                        Draft202012Validator(schema).validate(result.structured_content)
                    return result.structured_content

                await call("verificar_integracao", {})
                active = await call("listar_disciplinas", {})
                assert all(c["status"] == "ACTIVE" for c in active["disciplinas"])
                print("Disciplinas ativas na primeira página:", len(active["disciplinas"]))
                shared = await call("buscar_disciplina", {"nome": "Automação"})
                assert len(shared["disciplinas"]) == 1
                print("Alias da turma compartilhada: OK")
                if args.course_id:
                    data = await call("listar_materiais", {"disciplina_id": args.course_id})
                    print("Materiais reais na primeira página:", len(data["itens"]))
                    notices = await call("listar_avisos", {"disciplina_id": args.course_id})
                    print("Avisos reais na primeira página:", len(notices["itens"]))
                    denied = await session.call_tool("ler_pdf", {"disciplina_id": args.course_id, "arquivo_id": "unrelated_file"})
                    assert denied.is_error and denied.structured_content["erro"]["codigo"] == "arquivo_nao_vinculado"
                    print("Arquivo arbitrário recusado: OK")
                    if args.activities:
                        page, ids, due, iterations = None, set(), 0, 0
                        while True:
                            activities = await call("listar_atividades", {"disciplina_id": args.course_id, "pagina": page})
                            for item in activities["itens"]:
                                assert item["id"] not in ids and item["estado_publicacao"] == "PUBLISHED"
                                ids.add(item["id"])
                                due += bool(item["prazo"]["em_sao_paulo"])
                            page = activities["proxima_pagina"]
                            iterations += 1
                            assert iterations <= 10
                            if not page:
                                break
                        print("Atividades reais:", len(ids), "com prazo convertido:", due)
                        if ids:
                            activity_id = sorted(ids)[0]
                            detail = await call("detalhar_atividade", {"disciplina_id": args.course_id, "atividade_id": activity_id})
                            assert detail["atividade"]["id"] == activity_id and not detail["atividade"]["descricao_truncada"]
                        searched = await call("buscar_atividades", {"disciplina_id": args.course_id, "prazo": "com_prazo", "ordenacao": "prazo"})
                        assert all(i["prazo_data"] is not None for i in searched["resultados"])
                        own = await call("consultar_entregas", {"disciplina_id": args.course_id, "tamanho": 2})
                        assert all(i["disciplina_id"] == args.course_id for i in own["entregas"])
                        print("Detalhe, busca por prazos e entregas próprias: OK")
                        first = await call("listar_atividades", {"disciplina_id": args.course_id, "tamanho": 1})
                        if first["proxima_pagina"]:
                            second = await call("listar_atividades", {"disciplina_id": args.course_id, "tamanho": 1, "pagina": first["proxima_pagina"]})
                            assert not ({i["id"] for i in first["itens"]} & {i["id"] for i in second["itens"]})
                            print("Paginação real de atividades sem duplicação: OK")
                if args.course_id and args.file_id:
                    cursor, pages, chars, iterations = {"pagina_inicio": 1, "offset": 0}, set(), 0, 0
                    while cursor:
                        data = await call("ler_pdf", {"disciplina_id": args.course_id, "arquivo_id": args.file_id, **cursor})
                        pages.update(p["pagina"] for p in data["paginas"])
                        chars += sum(len(p["texto"]) for p in data["paginas"])
                        cursor = data["continuacao"]
                        iterations += 1
                        assert iterations <= 500
                    assert len(pages) == data["total_paginas"] and chars > 0
                    print("PDF real integral:", len(pages), "páginas,", chars, "caracteres,", iterations, "chamadas")
                if args.course_id and args.zip_file_id:
                    base_args = {"disciplina_id": args.course_id, "arquivo_id": args.zip_file_id}
                    inspection = await call("inspecionar_anexo", base_args)
                    assert inspection["conteudo_lido"] is False
                    cursor, entries, seen = None, [], set()
                    while True:
                        data = await call("listar_conteudo_zip", base_args | {"continuacao": cursor})
                        entries.extend(data["entradas"])
                        cursor = data["continuacao"]
                        if not cursor:
                            break
                        assert cursor not in seen and len(seen) < 100
                        seen.add(cursor)
                    print("ZIP real:", data["total_arquivos"], "arquivos,", len(entries), "entradas na estrutura")
                    path = args.zip_path or next((e["caminho"] for e in entries if e["leitura_permitida"] and e["caminho"].endswith("pom.xml")), None)
                    path = path or next((e["caminho"] for e in entries if e["leitura_permitida"]), None)
                    assert path, "ZIP sem arquivo textual permitido; escolha outro anexo"
                    offset, chars = 0, 0
                    while offset is not None:
                        result = await call("ler_arquivo_zip", base_args | {"caminho": path, "offset": offset})
                        assert result["conteudo_lido"] and result["sha256_zip"] == data["sha256_zip"]
                        chars += result["caracteres_retornados"]
                        next_offset = result["proximo_offset"]
                        assert next_offset is None or next_offset > offset
                        offset = next_offset
                    print("Texto real no ZIP:", chars, "caracteres lidos; conteúdo omitido do relatório")
    print("Validação remota concluída.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--course-id")
    parser.add_argument("--file-id")
    parser.add_argument("--zip-file-id", help="ID de ZIP vinculado à turma; exige --course-id")
    parser.add_argument("--zip-path", help="Caminho textual exato, opcional")
    parser.add_argument("--activities", action="store_true", help="Valida atividades, detalhe, prazos, paginação e entregas próprias")
    args = parser.parse_args()
    if (args.file_id or args.zip_file_id) and not args.course_id:
        parser.error("--file-id e --zip-file-id exigem --course-id")
    if args.zip_path and not args.zip_file_id:
        parser.error("--zip-path exige --zip-file-id")
    asyncio.run(verify(args))
