import asyncio
import json
import time
from contextvars import ContextVar

import httpx
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from .errors import ServiceError

budget: ContextVar[dict | None] = ContextVar("google_budget", default=None)


class BoundedRequest(Request):
    def __call__(self, *args, **kwargs):
        kwargs["timeout"] = 8
        return super().__call__(*args, **kwargs)


def spend(limit=60):
    value = budget.get()
    if value is None:
        value = {"calls": 0, "started": time.monotonic()}
        budget.set(value)
    value["calls"] += 1
    if value["calls"] > limit or time.monotonic() - value["started"] > 45:
        raise ServiceError("limite_consulta", "Consulta atingiu o limite de chamadas ou tempo. Restrinja a disciplina ou continue a paginação.", 429)


def google_error(status, payload=None):
    result = _google_error(status, payload)
    result.context["http_google"] = status
    return result


def _google_error(status, payload=None):
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    if not isinstance(error, dict):
        error = {}
    reasons = set()
    for key in ("details", "errors"):
        items = error.get(key)
        if isinstance(items, list):
            reasons.update(item.get("reason") for item in items if isinstance(item, dict) and isinstance(item.get("reason"), str))
    if status == 403:
        if reasons & {"downloadRestricted", "cannotDownloadFile", "fileNotDownloadable"}:
            return ServiceError("download_proibido", "O Google não permite baixar este conteúdo.", 403)
        if reasons & {"rateLimitExceeded", "userRateLimitExceeded", "downloadQuotaExceeded"}:
            return ServiceError("quota_google", "Limite do Google atingido. Tente novamente mais tarde.", 429)
        if reasons & {"ACCESS_TOKEN_SCOPE_INSUFFICIENT", "insufficientPermissions"}:
            return ServiceError("escopo_google_insuficiente", "O Google informou escopo insuficiente. Reautorize as capacidades de leitura necessárias.", 403)
        if reasons & {"ADMIN_POLICY_ENFORCED", "ORG_RESTRICTION_VIOLATION", "adminPolicyEnforced", "domainPolicy"}:
            return ServiceError("politica_institucional", "O Google informou uma restrição administrativa. Solicite autorização à instituição.", 403)
        if "SERVICE_DISABLED" in reasons:
            return ServiceError("api_google_desabilitada", "A API consultada não está habilitada no projeto Google.", 503)
    errors = {
        400: ("parametro_google", "O Google recusou os parâmetros da consulta.", 400),
        401: ("google_reautorizar", "Autorização Google expirada ou revogada. Reautorize a integração.", 503),
        403: ("google_sem_permissao", "O Google recusou o acesso sem informar uma causa reconhecida; não é possível concluir se é permissão, escopo ou política.", 403),
        404: ("nao_encontrado", "Recurso indisponível para a conta autorizada.", 404),
        429: ("quota_google", "Limite do Google atingido. Tente novamente mais tarde.", 429),
    }
    return ServiceError(*errors.get(status, ("google_indisponivel", "Serviço Google temporariamente indisponível.", 502)))


class GoogleClient:
    def __init__(self, settings):
        self.settings = settings
        self.credentials = {}
        self.lock = asyncio.Lock()
        self.semaphore = asyncio.Semaphore(4)

    async def token(self, kind):
        async with self.lock:
            raw = self.settings.classroom_credentials if kind == "classroom" else self.settings.drive_credentials
            if not raw:
                raise ServiceError("google_nao_configurado", "Credencial Google não configurada.", 503)
            try:
                if kind not in self.credentials:
                    self.credentials[kind] = Credentials.from_authorized_user_info(json.loads(raw))
                creds = self.credentials[kind]
                if not creds.valid:
                    await asyncio.wait_for(asyncio.to_thread(creds.refresh, BoundedRequest()), timeout=12)
                return creds.token
            except (ValueError, KeyError, GoogleAuthError, TimeoutError):
                raise ServiceError("google_reautorizar", "Não foi possível renovar a autorização Google. Reautorize a integração.", 503) from None

    async def get(self, path, params=None, kind="classroom", resource_key=None, credential_kind=None):
        base = "https://classroom.googleapis.com/v1/" if kind == "classroom" else "https://www.googleapis.com/drive/v3/"
        token = await self.token(credential_kind or kind)
        headers = {"Authorization": "Bearer " + token}
        if resource_key:
            headers["X-Goog-Drive-Resource-Keys"] = path.removeprefix("files/") + "/" + resource_key
        async with self.semaphore, httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            for attempt in range(3):
                spend(self.settings.max_google_calls)
                try:
                    response = await client.get(base + path, params=params, headers=headers)
                except httpx.RequestError:
                    if attempt == 2:
                        raise ServiceError("rede_google", "Falha de rede ao consultar o Google.", 504) from None
                    await asyncio.sleep(0.3 * 2**attempt)
                    continue
                if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                    await asyncio.sleep(0.3 * 2**attempt)
                    continue
                if response.status_code != 200:
                    try:
                        payload = response.json()
                    except ValueError:
                        payload = None
                    raise google_error(response.status_code, payload)
                return response.json()

    async def download(self, file_id, max_bytes=None, resource_key=None):
        limit = self.settings.max_pdf_bytes if max_bytes is None else max_bytes
        token = await self.token("drive")
        headers = {"Authorization": "Bearer " + token}
        if resource_key:
            headers["X-Goog-Drive-Resource-Keys"] = file_id + "/" + resource_key
        async with self.semaphore, httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            spend(self.settings.max_google_calls)
            try:
                async with client.stream("GET", f"https://www.googleapis.com/drive/v3/files/{file_id}", params={"alt": "media", "supportsAllDrives": "true"}, headers=headers) as response:
                    if response.status_code != 200:
                        body = bytearray()
                        async for chunk in response.aiter_bytes(4096):
                            body.extend(chunk[:65536 - len(body)])
                            if len(body) >= 65536:
                                break
                        try:
                            payload = json.loads(body)
                        except ValueError:
                            payload = None
                        raise google_error(response.status_code, payload)
                    data = bytearray()
                    async for chunk in response.aiter_bytes(65536):
                        if len(data) + len(chunk) > limit:
                            raise ServiceError("pdf_grande" if max_bytes is None else "arquivo_grande", "Arquivo excede o limite de download.", 413)
                        data.extend(chunk)
                    return bytes(data)
            except httpx.RequestError:
                raise ServiceError("rede_google", "Falha de rede ao baixar o arquivo. Tente novamente.", 504) from None

    def scopes(self):
        # Somente a resposta do servidor de autorização comprova a concessão.
        creds = self.credentials.get("classroom")
        granted = creds.granted_scopes if creds and creds.valid else None
        return granted.split() if isinstance(granted, str) else list(granted or [])

    async def identity_status(self):
        """Compara IDs oficiais Drive usando cada credencial; não retorna identidades."""
        try:
            classroom, drive = await asyncio.gather(
                self.get("about", {"fields": "user(permissionId)"}, kind="drive", credential_kind="classroom"),
                self.get("about", {"fields": "user(permissionId)"}, kind="drive"),
            )
            left = classroom.get("user", {}).get("permissionId")
            right = drive.get("user", {}).get("permissionId")
            return "mesma_conta" if left and left == right else "contas_diferentes" if left and right else "nao_confirmada"
        except ServiceError:
            return "nao_confirmada"
