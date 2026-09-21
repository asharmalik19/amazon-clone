"""Application settings, read from the environment with local-development defaults."""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Obviously-a-development-default. Production sets SECRET_KEY in the environment.
DEV_SECRET_KEY = "dev-only-insecure-secret-change-me"
DEV_DATABASE_URL = "sqlite:///./app.db"


@dataclass(frozen=True)
class Settings:
    """Runtime configuration for one process."""

    database_url: str
    secret_key: str
    port: int
    site_name: str

    @property
    def is_production(self) -> bool:
        """True when the secret key was supplied by the environment."""
        return self.secret_key != DEV_SECRET_KEY


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, built once."""
    return Settings(
        database_url=os.getenv("DATABASE_URL", DEV_DATABASE_URL),
        secret_key=os.getenv("SECRET_KEY", DEV_SECRET_KEY),
        port=int(os.getenv("PORT", "8000")),
        site_name=os.getenv("SITE_NAME", "amazonia"),
    )
