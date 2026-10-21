import json
import os
from dataclasses import dataclass, field
from pathlib import Path

BASE = Path(__file__).resolve().parent
READ_SCOPE = "classroom:read"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly",
    "https://www.googleapis.com/auth/classroom.announcements.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


@dataclass
class Settings:
    public_url: str = field(default_factory=lambda: os.getenv("PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/"))
    issuer: str = field(default_factory=lambda: os.getenv("MCP_OAUTH_ISSUER", ""))
    owner_sub: str = field(default_factory=lambda: os.getenv("MCP_OWNER_SUB", ""))
    classroom_credentials: str = field(default_factory=lambda: os.getenv("GOOGLE_CLASSROOM_CREDENTIALS", ""))
    drive_credentials: str = field(default_factory=lambda: os.getenv("GOOGLE_DRIVE_CREDENTIALS", ""))
    google_web_client: str = field(default_factory=lambda: os.getenv("GOOGLE_WEB_CLIENT", ""))
    cookie_secret: str = field(default_factory=lambda: os.getenv("OAUTH_STATE_SECRET", ""))
    max_pdf_bytes: int = 20 * 1024 * 1024
    max_pages: int = 5
    max_chars: int = 18000
    max_google_calls: int = 60
    request_seconds: int = 55
    aliases: dict = field(default_factory=lambda: json.loads((BASE / "aliases.json").read_text(encoding="utf-8")))

    @property
    def resource(self):
        return self.public_url + "/mcp"
