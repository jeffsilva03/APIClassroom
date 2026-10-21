import asyncio
import time
from collections import defaultdict, deque

import httpx
import jwt
from starlette.responses import JSONResponse

from .config import READ_SCOPE
from .errors import ServiceError
from .google import budget


class TokenVerifier:
    def __init__(self, settings):
        self.settings = settings
        self.keys = None
        self.cached_at = 0
        self.lock = asyncio.Lock()

    async def verify(self, token):
        s = self.settings
        if not s.issuer or not s.owner_sub:
            raise ServiceError("oauth_nao_configurado", "Autenticação ainda não configurada.", 503)
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not header.get("kid"):
                raise ValueError()
            async with self.lock:
                if not self.keys or time.monotonic() - self.cached_at > 300:
                    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
                        r = await client.get(s.issuer.rstrip("/") + "/.well-known/jwks.json")
                        r.raise_for_status()
                        self.keys = r.json()["keys"]
                        self.cached_at = time.monotonic()
            key = next(k for k in self.keys if k.get("kid") == header["kid"])
            claims = jwt.decode(token, jwt.PyJWK.from_dict(key).key, algorithms=["RS256"], audience=s.resource, issuer=s.issuer, options={"require": ["exp", "iat", "iss", "aud", "sub"]})
        except httpx.HTTPError:
            raise ServiceError("oauth_indisponivel", "Não foi possível verificar a autorização.", 503) from None
        except (jwt.PyJWTError, ValueError, KeyError, StopIteration, TypeError):
            raise ServiceError("token_invalido", "Token inválido ou expirado.", 401) from None
        if claims["sub"] != s.owner_sub:
            raise ServiceError("identidade_nao_autorizada", "Identidade sem acesso a esta integração pessoal.", 403)
        if READ_SCOPE not in claims.get("scope", "").split():
            raise ServiceError("escopo_insuficiente", "Escopo classroom:read necessário.", 403)
        return claims


class SecurityMiddleware:
    def __init__(self, app, settings, verifier):
        self.app, self.settings, self.verifier = app, settings, verifier
        self.requests = defaultdict(deque)
        self.concurrent = asyncio.Semaphore(4)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        headers = dict(scope.get("headers", []))
        public = path in {"/", "/health", "/privacy"} or path.startswith("/.well-known/")
        if public:
            return await self.app(scope, receive, send)
        challenge = f'Bearer resource_metadata="{self.settings.public_url}/.well-known/oauth-protected-resource", scope="{READ_SCOPE}"'
        try:
            if b"origin" in headers and headers[b"origin"].decode() not in self.settings.allowed_origins:
                raise ServiceError("origem_nao_permitida", "Origem não permitida.", 403)
            if int(headers.get(b"content-length", b"0")) > 65536:
                raise ServiceError("corpo_grande", "Requisição excede 64 KB.", 413)
            auth = headers.get(b"authorization", b"").decode()
            if not auth.startswith("Bearer ") or len(auth) > 16384:
                raise ServiceError("autenticacao_necessaria", "Autenticação OAuth necessária.", 401)
            claims = await self.verifier.verify(auth[7:])
            scope.setdefault("state", {})["identity"] = claims["sub"]
            now = time.monotonic()
            queue = self.requests[claims["sub"]]
            while queue and now - queue[0] > 60:
                queue.popleft()
            if len(queue) >= 60:
                raise ServiceError("limite_requisicoes", "Limite de 60 requisições por minuto nesta instância.", 429)
            queue.append(now)
        except (ServiceError, ValueError) as exc:
            err = exc if isinstance(exc, ServiceError) else ServiceError("requisicao_invalida", "Requisição inválida.", 400)
            scope.setdefault("state", {})["mcp_rejection"] = err.code
            extra = {"WWW-Authenticate": challenge} if err.status in (401, 403) else {}
            if err.status == 429:
                extra["Retry-After"] = "60"
            return await JSONResponse(err.payload(), status_code=err.status, headers={**extra, "Cache-Control": "no-store"})(scope, receive, send)
        budget_token = budget.set({"calls": 0, "started": time.monotonic()})
        consumed = 0
        started = False

        async def bounded_receive():
            nonlocal consumed
            message = await receive()
            consumed += len(message.get("body", b""))
            if consumed > 65536:
                raise ServiceError("corpo_grande", "Requisição excede 64 KB.", 413)
            return message

        async def secured_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message.setdefault("headers", []).extend([(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer")])
            await send(message)

        try:
            async with asyncio.timeout(self.settings.request_seconds):
                async with self.concurrent:
                    await self.app(scope, bounded_receive, secured_send)
        except TimeoutError:
            if not started:
                error = ServiceError("tempo_excedido", "Consulta excedeu o tempo disponível. Restrinja o intervalo e tente novamente.", 504)
                await JSONResponse(error.payload(), status_code=504, headers={"Cache-Control": "no-store"})(scope, receive, send)
        finally:
            budget.reset(budget_token)
