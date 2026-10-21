"""Teste real pelo cliente oficial MCP; exibe apenas resultados agregados."""
import argparse
import asyncio
import json
from pathlib import Path

import httpx
import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def verify(args):
    token = json.loads(args.token_file.read_text())["access_token"]
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
    print("HTTPS, metadados e proteção anônima: OK")
    async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + token}, timeout=60) as http:
        async with streamable_http_client(base + "/mcp", http_client=http) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=60) as session:
                init = await session.initialize()
                tools = await session.list_tools()
                print("MCP inicializado:", init.server_info.name, "ferramentas:", len(tools.tools))
                assert len(tools.tools) == 11

                async def call(name, arguments):
                    result = await session.call_tool(name, arguments)
                    if result.is_error:
                        code = (result.structured_content or {}).get("erro", {}).get("codigo", "erro_mcp")
                        raise AssertionError(name + ": " + code)
                    assert result.structured_content is not None
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
    print("Validação remota concluída.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--course-id")
    parser.add_argument("--file-id")
    asyncio.run(verify(parser.parse_args()))
