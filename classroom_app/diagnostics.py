"""Diagnóstico MCP opcional: nunca registra cabeçalhos, parâmetros ou respostas."""
import json
import logging
import time

logger = logging.getLogger("classroom.mcp_diagnostics")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.propagate = False

RPC_METHODS = {"initialize", "notifications/initialized", "tools/list", "tools/call", "ping"}


class MCPDiagnosticsMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] not in {"/mcp", "/mcp/"}:
            return await self.app(scope, receive, send)
        started, status, body = time.monotonic(), 500, bytearray()
        rpc = "nao_inspecionado"
        headers = dict(scope.get("headers", []))
        auth = "auth_presente" if b"authorization" in headers else "auth_ausente"
        origin = {None: "origin_ausente", b"https://chatgpt.com": "origin_chatgpt", b"https://chat.openai.com": "origin_chatgpt_legado"}.get(headers.get(b"origin"), "origin_outro")

        async def observed_receive():
            nonlocal rpc
            message = await receive()
            if message["type"] == "http.request":
                if len(body) + len(message.get("body", b"")) <= 65536:
                    body.extend(message.get("body", b""))
                if not message.get("more_body", False):
                    try:
                        method = json.loads(body).get("method")
                        rpc = method if method in RPC_METHODS else "outro"
                    except (ValueError, AttributeError, TypeError):
                        rpc = "json_invalido"
                    body.clear()
            return message

        async def observed_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, observed_receive, observed_send)
        finally:
            reason = scope.get("state", {}).get("mcp_rejection")
            reason = reason or {421: "host_nao_permitido", 504: "tempo_excedido"}.get(status, "ok" if status < 400 else "erro_http")
            method = scope["method"] if scope["method"] in {"POST", "GET", "DELETE", "OPTIONS"} else "OUTRO"
            logger.info(json.dumps({"method": method, "route": "/mcp", "status": status, "duration_ms": round((time.monotonic() - started) * 1000), "reason": ":".join((reason, rpc, auth, origin))}))
