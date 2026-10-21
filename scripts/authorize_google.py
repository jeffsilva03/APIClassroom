"""Autoriza uma vez, renova e valida os acessos antes de publicar segredos."""
import argparse
import hmac
import json
import os
import shutil
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from google_auth_oauthlib.flow import InstalledAppFlow

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from classroom_app.config import GOOGLE_SCOPES
from classroom_app.errors import ServiceError
from classroom_app.google_authorization import ACTIVITY_SCOPE, LEGACY_ACTIVITY_SCOPE, validate_credentials


def authorize(args):
    requested = [LEGACY_ACTIVITY_SCOPE if args.diagnose_scope_change and s == ACTIVITY_SCOPE else s for s in GOOGLE_SCOPES]
    flow = InstalledAppFlow.from_client_secrets_file(str(args.credentials), requested)
    result, finished = {}, False

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass  # A URL de callback contém um código OAuth; nunca registre.

        def do_GET(self):
            nonlocal finished
            path = urlsplit(self.path)
            if path.path == "/start":
                self.send_response(302)
                self.send_header("Location", auth_url)
                self.end_headers()
                return
            if path.path == "/callback":
                query = parse_qs(path.query)
                if not hmac.compare_digest(query.get("state", [""])[0], state):
                    self.send_response(400)
                    self.end_headers()
                    return
                try:
                    if query.get("error"):
                        raise ValueError()
                    flow.fetch_token(authorization_response=f"https://127.0.0.1:{server.server_port}" + self.path)
                    result["credentials"] = json.loads(flow.credentials.to_json())
                    result["requested_scopes"] = requested
                    result["returned_scopes"] = flow.oauth2session.token.get("scope")
                except Exception:
                    result["error"] = "O Google não concluiu a autorização. Nenhum segredo foi alterado."
                self.send_response(302)
                self.send_header("Location", "/done")
                self.end_headers()
                return
            if path.path == "/done" and result:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b'Autorizacao recebida para validacao. Pode voltar ao chat.')
                finished = True
                return
            self.send_response(404)
            self.end_headers()

    with HTTPServer(("127.0.0.1", args.port), Handler) as server:
        server.timeout = 1
        flow.redirect_uri = f"http://127.0.0.1:{server.server_port}/callback"
        auth_url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="false", login_hint=args.expected_email)
        print(f"Autorize a conta acadêmica em http://127.0.0.1:{server.server_port}/start", flush=True)
        until = time.monotonic() + args.timeout
        previous = os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE")
        try:
            if args.diagnose_scope_change:
                os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
            while not finished and time.monotonic() < until:
                server.handle_request()
        finally:
            if previous is None:
                os.environ.pop("OAUTHLIB_RELAX_TOKEN_SCOPE", None)
            else:
                os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = previous
    if not result.get("credentials"):
        raise ServiceError("oauth_nao_concluido", result.get("error", "O consentimento não foi concluído no prazo disponível."), 422)
    print(json.dumps({"requested_scopes": result["requested_scopes"], "returned_scopes": result["returned_scopes"]}, ensure_ascii=True))
    return result["credentials"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", type=Path, default=Path("credentials.json"))
    parser.add_argument("--reuse", type=Path, help="Renova e valida uma credencial salva, sem novo consentimento")
    parser.add_argument("--output", type=Path, default=Path(".local/google-authorized-activities.json"))
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--expected-email", required=True)
    parser.add_argument("--probe-course")
    parser.add_argument("--diagnose-scope-change", action="store_true", help="Diagnóstico isolado do nome antigo; não configura relaxamento na Vercel")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--no-deploy", action="store_true")
    parser.add_argument("--vercel-scope")
    args = parser.parse_args()
    if os.getenv("OAUTHLIB_RELAX_TOKEN_SCOPE") and not args.diagnose_scope_change:
        raise SystemExit("Remova OAUTHLIB_RELAX_TOKEN_SCOPE do ambiente; use o diagnóstico isolado se necessário.")
    if not args.output.resolve().is_relative_to((Path.cwd() / ".local").resolve()):
        raise SystemExit("Salve credenciais somente na pasta .local ignorada pelo Git.")
    try:
        source = json.loads(args.reuse.read_text(encoding="utf-8")) if args.reuse else authorize(args)
        data, report = validate_credentials(source, args.expected_email, args.probe_course)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(".tmp")
        temporary.write_text(json.dumps(data), encoding="utf-8")
        temporary.replace(args.output)
        print(json.dumps(report, ensure_ascii=True, indent=2))
        print("Credencial validada salva na pasta local ignorada pelo Git.")
        if args.publish:
            command = shutil.which("vercel")
            base = [command] if command else [shutil.which("npx.cmd") or shutil.which("npx"), "--yes", "vercel@65.0.0"]
            scope_args = ["--scope", args.vercel_scope] if args.vercel_scope else []
            for key in ("GOOGLE_CLASSROOM_CREDENTIALS", "GOOGLE_DRIVE_CREDENTIALS"):
                published = subprocess.run([*base, "env", "add", key, "--environment", "production", "--type", "secret", "--force", *scope_args], input=json.dumps(data), text=True, capture_output=True, timeout=90)
                if published.returncode:
                    raise ServiceError("publicacao_recusada", "Falha na atualização de variável. Saída da CLI suprimida para proteger credenciais.", 422)
                print(key + " atualizada.")
            if not args.no_deploy:
                subprocess.run([*base, "deploy", "--prod", "--yes", *scope_args], check=True)
    except ServiceError as exc:
        raise SystemExit(exc.code + ": " + exc.message) from None
    except (OSError, ValueError, subprocess.SubprocessError):
        raise SystemExit("Não foi possível concluir a autorização/publicação; detalhes privados suprimidos.") from None


if __name__ == "__main__":
    main()
