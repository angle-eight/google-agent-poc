"""Configuration shared by the local app and deployment CLI."""

import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv

RESOURCE_PATTERN = re.compile(r"projects/[^/]+/locations/[^/]+/reasoningEngines/[^/]+")


@dataclass(frozen=True)
class Settings:
    backend: str = "local"
    project: str = ""
    location: str = "us-central1"
    model_location: str = "global"
    model: str = "gemini-3.5-flash"
    staging_bucket: str = ""
    resource_name: str = ""
    session_secret: str = ""
    cookie_secure: bool = False
    service_account: str = ""

    @classmethod
    def from_env(cls):
        load_dotenv(override=False)
        settings = cls(
            backend=os.getenv("APP_BACKEND", "local"),
            project=os.getenv("GOOGLE_CLOUD_PROJECT", ""),
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
            model_location=os.getenv("MODEL_LOCATION", "global"),
            model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
            staging_bucket=os.getenv("GOOGLE_CLOUD_STAGING_BUCKET", ""),
            resource_name=os.getenv("AGENT_ENGINE_RESOURCE_NAME", ""),
            session_secret=os.getenv("SESSION_SECRET", ""),
            cookie_secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
            service_account=os.getenv("AGENT_SERVICE_ACCOUNT", ""),
        )
        if settings.backend not in {"local", "remote"}:
            raise ValueError("APP_BACKEND は local / remote のいずれかです。")
        return settings

    def require_cloud(self):
        if not self.project or self.project == "your-project-id":
            raise ValueError("GOOGLE_CLOUD_PROJECT に実際のプロジェクトIDを設定してください。")

    def require_remote(self):
        self.require_cloud()
        if not RESOURCE_PATTERN.fullmatch(self.resource_name):
            raise ValueError("AGENT_ENGINE_RESOURCE_NAME に完全なリソース名を設定してください。")
        if len(self.session_secret) < 32:
            raise ValueError("remote モードには32文字以上の SESSION_SECRET が必要です。")
