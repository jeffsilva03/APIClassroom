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


def google_error(status):
    errors = {
        400: ("parametro_google", "O Google recusou os parâmetros da consulta.", 400),
        401: ("google_reautorizar", "Autorização Google expirada ou revogada. Reautorize a integração.", 503),
        403: ("google_sem_permissao", "O Google recusou o acesso. Verifique escopos e políticas institucionais.", 403),
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

    async def get(self, path, params=None, kind="classroom"):
        base = "https://classroom.googleapis.com/v1/" if kind == "classroom" else "https://www.googleapis.com/drive/v3/"
        token = await self.token(kind)
        async with self.semaphore, httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            for attempt in range(3):
                spend(self.settings.max_google_calls)
                try:
                    response = await client.get(base + path, params=params, headers={"Authorization": "Bearer " + token})
                except httpx.RequestError:
                    if attempt == 2:
                        raise ServiceError("rede_google", "Falha de rede ao consultar o Google.", 504) from None
                    await asyncio.sleep(0.3 * 2**attempt)
                    continue
                if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                    await asyncio.sleep(0.3 * 2**attempt)
                    continue
                if response.status_code != 200:
                    raise google_error(response.status_code)
                return response.json()

    async def download(self, file_id):
        token = await self.token("drive")
        async with self.semaphore, httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            spend(self.settings.max_google_calls)
            try:
                async with client.stream("GET", f"https://www.googleapis.com/drive/v3/files/{file_id}", params={"alt": "media"}, headers={"Authorization": "Bearer " + token}) as response:
                    if response.status_code != 200:
                        raise google_error(response.status_code)
                    data = bytearray()
                    async for chunk in response.aiter_bytes(65536):
                        if len(data) + len(chunk) > self.settings.max_pdf_bytes:
                            raise ServiceError("pdf_grande", "PDF excede o limite de 20 MB.", 413)
                        data.extend(chunk)
                    return bytes(data)
            except httpx.RequestError:
                raise ServiceError("rede_google", "Falha de rede ao baixar o PDF. Tente novamente.", 504) from None

    def scopes(self):
        try:
            return json.loads(self.settings.classroom_credentials).get("scopes", [])
        except (ValueError, TypeError):
            return []
