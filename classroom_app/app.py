import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from mcp.server.transport_security import TransportSecuritySettings

from .config import READ_SCOPE, Settings
from .courses import Courses
from .documents import Documents
from .diagnostics import MCPDiagnosticsMiddleware
from .errors import ServiceError
from .google import GoogleClient
from .materials import Materials
from .mcp_server import build_mcp
from .security import SecurityMiddleware, TokenVerifier

# Bibliotecas HTTP não devem registrar URLs privadas nem corpos retornados.
for name in ("httpx", "httpcore", "mcp", "google.auth", "pypdf"):
    logging.getLogger(name).setLevel(logging.CRITICAL)


def create_app(settings=None, google=None, verifier=None):
    settings = settings or Settings()
    google = google or GoogleClient(settings)
    courses = Courses(google, settings)
    materials = Materials(google, courses)
    documents = Documents(google, materials, settings)

    async def diagnostic():
        await google.get("courses", {"pageSize": 1, "courseStates": "ACTIVE"})
        await google.get("about", {"fields": "user(permissionId)"}, kind="drive")
        return {"status": "ok", "classroom": "conectado", "drive": "conectado", "atividades": "autorizadas" if "https://www.googleapis.com/auth/classroom.coursework.me.readonly" in google.scopes() else "capacidade_nao_autorizada", "armazenamento_pdfs": "somente_memoria", "modo": "somente_leitura"}

    mcp = build_mcp(courses, materials, documents, diagnostic)
    mcp_app = mcp.streamable_http_app(stateless_http=True, json_response=True, max_request_body_size=65536, transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=settings.allowed_hosts, allowed_origins=settings.allowed_origins))

    @asynccontextmanager
    async def lifespan(app):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    app = FastAPI(title="APIClassroom", version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.services = (courses, materials, documents)
    app.state.mcp = mcp
    app.add_middleware(SecurityMiddleware, settings=settings, verifier=verifier or TokenVerifier(settings))
    if settings.mcp_diagnostics:
        app.add_middleware(MCPDiagnosticsMiddleware)

    @app.exception_handler(ServiceError)
    async def service_error(request, exc):
        return JSONResponse(exc.payload(), status_code=exc.status)

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        return JSONResponse(ServiceError("falha_interna", "Falha interna ao processar a solicitação.", 500).payload(), status_code=500)

    @app.get("/", response_class=HTMLResponse)
    async def home():
        return '<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>APIClassroom</title><h1>APIClassroom</h1><p>Integração pessoal, somente leitura, com Google Classroom e Drive. O acesso aos materiais exige autorização OAuth.</p><a href="/privacy">Privacidade</a></html>'

    @app.get("/privacy", response_class=HTMLResponse)
    async def privacy():
        return '<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Privacidade — APIClassroom</title><h1>Privacidade</h1><p>Aplicação pessoal do proprietário. Acessa disciplinas, materiais, avisos e PDFs do Google apenas por autorização de leitura. Não publica dados acadêmicos. Os documentos são processados em memória e descartados após a resposta. Credenciais ficam em variáveis protegidas da hospedagem; não são enviadas ao cliente MCP. O texto consultado é enviado ao cliente autenticado, sujeito às políticas desse cliente. A autorização pode ser revogada na conta Google e no provedor de identidade. Não há venda de dados nem rastreamento publicitário.</p></html>'

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "1.0.0"}

    @app.get("/.well-known/oauth-protected-resource")
    @app.get("/.well-known/oauth-protected-resource/mcp")
    async def protected_metadata():
        return {"resource": settings.resource, "authorization_servers": [settings.issuer] if settings.issuer else [], "scopes_supported": [READ_SCOPE], "bearer_methods_supported": ["header"], "resource_name": "APIClassroom"}

    @app.get("/integracao")
    async def integration():
        return await diagnostic()

    @app.get("/disciplinas")
    async def list_courses(incluir_arquivadas: bool = False, tamanho: int = Query(50, ge=1, le=100), pagina: str | None = None, busca: str | None = None):
        return await courses.search(busca, incluir_arquivadas) if busca else await courses.list(incluir_arquivadas, tamanho, pagina)

    @app.get("/disciplinas/{course_id}")
    async def detail_course(course_id: str, incluir_arquivadas: bool = False):
        return await courses.detail(course_id, incluir_arquivadas)

    @app.get("/disciplinas/{course_id}/materiais")
    async def list_materials(course_id: str, tamanho: int = Query(50, ge=1, le=100), pagina: str | None = None, incluir_arquivadas: bool = False):
        return await materials.list(course_id, tamanho, pagina, incluir_arquivadas)

    @app.get("/disciplinas/{course_id}/arquivos")
    async def list_files(course_id: str, tamanho: int = Query(50, ge=1, le=100), pagina: str | None = None, incluir_arquivadas: bool = False):
        return await materials.files(course_id, tamanho, pagina, incluir_arquivadas)

    @app.get("/disciplinas/{course_id}/arquivos/{file_id}/texto")
    async def read_pdf(course_id: str, file_id: str, pagina: int = Query(1, ge=1), pagina_fim: int | None = None, offset: int = Query(0, ge=0), incluir_arquivadas: bool = False):
        return await documents.read(course_id, file_id, pagina, pagina_fim, offset, incluir_arquivadas)

    @app.get("/disciplinas/{course_id}/avisos")
    async def announcements(course_id: str, tamanho: int = Query(50, ge=1, le=100), pagina: str | None = None, incluir_arquivadas: bool = False):
        return await materials.list(course_id, tamanho, pagina, incluir_arquivadas, kind="announcements")

    @app.get("/disciplinas/{course_id}/atividades")
    async def coursework(course_id: str, tamanho: int = Query(50, ge=1, le=100), pagina: str | None = None, incluir_arquivadas: bool = False):
        return await materials.list(course_id, tamanho, pagina, incluir_arquivadas, kind="courseWork")

    @app.get("/pesquisa/materiais")
    async def search_materials(consulta: str, disciplina_id: str | None = None, disciplina_offset: int = Query(0, ge=0), pagina: str | None = None, incluir_arquivadas: bool = False):
        return await materials.search(consulta, disciplina_id, disciplina_offset, pagina, incluir_arquivadas)

    @app.get("/pesquisa/documentos")
    async def search_documents(disciplina_id: str, arquivo_id: str, consulta: str, pagina: int = Query(1, ge=1), offset: int = Query(0, ge=0), incluir_arquivadas: bool = False):
        return await documents.search(disciplina_id, arquivo_id, consulta, pagina, offset, incluir_arquivadas)

    app.mount("/", mcp_app)
    return app


app = create_app()
