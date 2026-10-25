import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

BASE = Path(__file__).resolve().parent
READ_SCOPE = "classroom:read"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly",
    "https://www.googleapis.com/auth/classroom.announcements.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/classroom.student-submissions.me.readonly",
]


@dataclass
class Settings:
    public_url: str = field(default_factory=lambda: os.getenv("PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/"))
    issuer: str = field(default_factory=lambda: os.getenv("MCP_OAUTH_ISSUER", ""))
    owner_sub: str = field(default_factory=lambda: os.getenv("MCP_OWNER_SUB", ""))
    classroom_credentials: str = field(default_factory=lambda: os.getenv("GOOGLE_CLASSROOM_CREDENTIALS", ""))
    drive_credentials: str = field(default_factory=lambda: os.getenv("GOOGLE_DRIVE_CREDENTIALS", ""))
    max_pdf_bytes: int = 20 * 1024 * 1024
    max_pages: int = 5
    max_chars: int = 18000
    max_zip_bytes: int = field(default_factory=lambda: int(os.getenv("MAX_ZIP_BYTES", 20 * 1024 * 1024)))
    max_zip_expanded: int = field(default_factory=lambda: int(os.getenv("MAX_ZIP_EXPANDED", 50 * 1024 * 1024)))
    max_zip_entries: int = field(default_factory=lambda: int(os.getenv("MAX_ZIP_ENTRIES", 2000)))
    max_zip_file: int = field(default_factory=lambda: int(os.getenv("MAX_ZIP_FILE", 2 * 1024 * 1024)))
    max_zip_ratio: int = field(default_factory=lambda: int(os.getenv("MAX_ZIP_RATIO", 100)))
    zip_seconds: int = field(default_factory=lambda: int(os.getenv("ZIP_SECONDS", 10)))
    zip_chars: int = field(default_factory=lambda: int(os.getenv("ZIP_CHARS", 18000)))
    max_google_calls: int = 60
    request_seconds: int = 55
    mcp_diagnostics: bool = field(default_factory=lambda: os.getenv("MCP_DIAGNOSTICS", "0") == "1")
    aliases: dict = field(default_factory=lambda: json.loads((BASE / "aliases.json").read_text(encoding="utf-8")))

    @property
    def resource(self):
        return self.public_url + "/mcp"

    @property
    def allowed_hosts(self):
        return [urlsplit(self.public_url).netloc]

    @property
    def allowed_origins(self):
        # Mesma política no middleware OAuth e no transporte MCP; sem curingas.
        return [self.public_url, "https://chatgpt.com", "https://chat.openai.com"]
