"""Reautoriza a conta Google e atualiza segredos sem imprimir seus valores."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import AuthorizedSession

SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly",
    "https://www.googleapis.com/auth/classroom.announcements.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--expected-email", required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    flow = InstalledAppFlow.from_client_secrets_file(str(args.credentials), SCOPES)
    creds = flow.run_local_server(host="127.0.0.1", port=args.port, open_browser=False, access_type="offline", prompt="consent", authorization_prompt_message="Autorize a conta acadêmica no navegador:\n{url}", success_message="Autorizacao concluida. Volte ao chat.", timeout_seconds=600)
    if not creds.refresh_token or not creds.has_scopes(SCOPES):
        raise SystemExit("Autorização incompleta. Nenhum segredo de produção foi alterado.")
    with AuthorizedSession(creds) as session:
        response = session.get("https://www.googleapis.com/drive/v3/about", params={"fields": "user(emailAddress)"}, timeout=15)
        response.raise_for_status()
        if response.json().get("user", {}).get("emailAddress", "").casefold() != args.expected_email.casefold():
            raise SystemExit("A conta autorizada não corresponde à conta acadêmica esperada. Nenhum segredo de produção foi alterado.")
    data = json.loads(creds.to_json())
    data = {k: v for k, v in data.items() if k in {"client_id", "client_secret", "refresh_token", "token_uri", "scopes"}}
    output = Path(".local/google-authorized.json")
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(data), encoding="utf-8")
    print("Credencial salva na pasta local ignorada pelo Git.")
    if args.publish:
        command = shutil.which("vercel")
        base = [command] if command else [shutil.which("npx.cmd") or shutil.which("npx"), "--yes", "vercel@65.0.0"]
        for key in ("GOOGLE_CLASSROOM_CREDENTIALS", "GOOGLE_DRIVE_CREDENTIALS"):
            result = subprocess.run([*base, "env", "add", key, "--environment", "production", "--type", "secret", "--force"], input=json.dumps(data), text=True, capture_output=True, timeout=90)
            if result.returncode:
                raise SystemExit("Falha na atualização da variável. Saída da CLI suprimida para proteger credenciais.")
            print(key + " atualizada.")
        subprocess.run([*base, "deploy", "--prod", "--yes"], check=True)


if __name__ == "__main__":
    main()
