"""Validação de credenciais antes da publicação, com relatório sem segredos."""
import httpx

from .config import GOOGLE_SCOPES
from .errors import ServiceError

ACTIVITY_SCOPE = "https://www.googleapis.com/auth/classroom.student-submissions.me.readonly"
LEGACY_ACTIVITY_SCOPE = "https://www.googleapis.com/auth/classroom.coursework.me.readonly"
BASE_SCOPES = set(GOOGLE_SCOPES) - {ACTIVITY_SCOPE}
TOKEN_URI = "https://oauth2.googleapis.com/token"


def granted_scopes(value):
    values = value.split() if isinstance(value, str) else value
    if not isinstance(values, (list, tuple, set)) or any(not isinstance(s, str) for s in values):
        raise ServiceError("escopos_nao_confirmados", "O Google não informou os escopos efetivamente concedidos.", 422)
    return set(values)


def validate_credentials(data, expected_email, probe_course=None, client=None):
    """Renova e comprova cada acesso antes de permitir a publicação."""
    fields = {key: data.get(key) for key in ("client_id", "client_secret", "refresh_token")}
    if not all(isinstance(v, str) and v for v in fields.values()) or data.get("token_uri", TOKEN_URI) != TOKEN_URI:
        raise ServiceError("credencial_incompleta", "Credencial incompleta; preserve as credenciais funcionais.", 422)
    if client is None:
        with httpx.Client(timeout=20, follow_redirects=False) as http:
            return validate_credentials(data, expected_email, probe_course, http)
    try:
        refreshed = client.post(TOKEN_URI, data={"grant_type": "refresh_token", **fields})
        if refreshed.status_code != 200:
            raise ServiceError("google_reautorizar", "O Google recusou a renovação. Nenhum segredo foi alterado.", 422)
        payload = refreshed.json()
        scopes = granted_scopes(payload.get("scope"))
        if not BASE_SCOPES <= scopes or not scopes & {ACTIVITY_SCOPE, LEGACY_ACTIVITY_SCOPE}:
            raise ServiceError("autorizacao_incompleta", "As credenciais não preservam os acessos anteriores e a leitura de atividades.", 422)
        if scopes - (BASE_SCOPES | {ACTIVITY_SCOPE, LEGACY_ACTIVITY_SCOPE}):
            raise ServiceError("escopos_inesperados", "O Google concedeu escopos adicionais. Revise a autorização antes de publicar.", 422)
        headers = {"Authorization": "Bearer " + payload["access_token"]}
        report = {"refresh_http": 200, "granted_scopes": sorted(scopes), "probes": {}}

        def probe(name, url, params):
            response = client.get(url, params=params, headers=headers)
            report["probes"][name] = {"http": response.status_code}
            if response.status_code != 200:
                raise ServiceError("validacao_google_recusada", "Uma capacidade necessária foi recusada pelo Google. Preserve as credenciais atuais.", 422)
            return response.json()

        about = probe("drive", "https://www.googleapis.com/drive/v3/about", {"fields": "user(emailAddress)"})
        if about.get("user", {}).get("emailAddress", "").casefold() != expected_email.casefold():
            raise ServiceError("conta_google_incorreta", "A conta autorizada não corresponde à conta acadêmica esperada.", 422)
        report["expected_account"] = True
        courses, cursor, seen = {}, None, set()
        while True:
            params = {"pageSize": 100, "courseStates": "ACTIVE"}
            if cursor:
                params["pageToken"] = cursor
            page = probe("courses", "https://classroom.googleapis.com/v1/courses", params)
            courses.update({c["id"]: c for c in page.get("courses", []) if c.get("courseState") == "ACTIVE"})
            cursor = page.get("nextPageToken")
            if not cursor:
                break
            if cursor in seen or len(seen) >= 20:
                raise ServiceError("paginacao_google", "Não foi possível validar a paginação das disciplinas.", 422)
            seen.add(cursor)
        course = probe_course or next(iter(courses), None)
        if course not in courses:
            raise ServiceError("disciplina_validacao", "Escolha uma disciplina ativa da conta para validar a autorização.", 422)
        root = f"https://classroom.googleapis.com/v1/courses/{course}/"
        for name, suffix, params, key in (
            ("materials", "courseWorkMaterials", {"pageSize": 1, "courseWorkMaterialStates": "PUBLISHED"}, "courseWorkMaterial"),
            ("announcements", "announcements", {"pageSize": 1, "announcementStates": "PUBLISHED"}, "announcements"),
            ("activities", "courseWork", {"pageSize": 1, "courseWorkStates": "PUBLISHED"}, "courseWork"),
            ("own_submissions", "courseWork/-/studentSubmissions", {"pageSize": 1, "userId": "me"}, "studentSubmissions"),
        ):
            result = probe(name, root + suffix, params)
            report["probes"][name].update(count=len(result.get(key, [])), has_next_page=bool(result.get("nextPageToken")))
        return fields | {"token_uri": TOKEN_URI, "scopes": sorted(scopes)}, report
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise ServiceError("validacao_google_indisponivel", "Não foi possível validar a resposta Google com segurança. Nenhum segredo foi alterado.", 422) from None
