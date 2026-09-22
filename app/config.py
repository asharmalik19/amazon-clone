"""Application settings, read from the environment with local-development defaults."""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Obviously-a-development-default. Production sets SECRET_KEY in the environment.
DEV_SECRET_KEY = "dev-only-insecure-secret-change-me"
DEV_DATABASE_URL = "sqlite:///./app.db"


def normalize_database_url(url: str) -> str:
    """Return `url` with an explicit SQLAlchemy driver for Postgres.

    Managed Postgres providers hand out `postgres://` or `postgresql://` URLs. Bare
    `postgresql://` makes SQLAlchemy reach for psycopg2, which this project does not
    install -- it uses psycopg 3. Pinning the driver in the URL means the same
    environment variable works unedited against Render, any other provider, and a
    local Postgres, while SQLite URLs pass through untouched.
    """
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


# What a platform's environment editor produces when someone means yes or no. A value
# outside both lists is not silently read as "no": that would turn a typo into a quietly
# disabled security flag.
_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def env_flag(name: str) -> bool | None:
    """The boolean `name` names, or `None` when it is unset, blank, or unrecognised.

    Three states rather than two, because "unset" is a real answer: the caller gets to
    fall back to a default of its own rather than to `False`. An env var created but left
    empty -- the easy mistake to make in a dashboard -- counts as unset, exactly as
    `DATABASE_URL` does above.
    """
    raw = os.getenv(name, "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    return None


@dataclass(frozen=True)
class Settings:
    """Runtime configuration for one process."""

    database_url: str
    secret_key: str
    port: int
    site_name: str

    database_url_from_env: bool

    # `COOKIE_SECURE`, when it says anything. `None` means "nobody said", which is the
    # usual case locally and the case the property below has an opinion about.
    cookie_secure_override: bool | None = None

    @property
    def is_production(self) -> bool:
        """True when the secret key was supplied by the environment."""
        return self.secret_key != DEV_SECRET_KEY

    @property
    def cookie_secure(self) -> bool:
        """Whether the cart cookie is sent with the `Secure` flag.

        The declaration wins, and `render.yaml` makes it. The fallback matters anyway:
        a deploy someone stands up without that line still gets a `Secure` cookie rather
        than being insecure by omission.

        It is not derived from the request's scheme, because behind a TLS-terminating
        proxy the scheme only arrives in `X-Forwarded-Proto` -- a header any client can
        set. A security flag should not be decided by attacker-supplied text when a
        boolean in the blueprint says the same thing and cannot be spoofed.
        """
        if self.cookie_secure_override is not None:
            return self.cookie_secure_override
        return self.is_production


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, built once."""
    # An empty string counts as absent: a platform env var that was created but left
    # blank should fall back to the local default, not produce an unusable URL.
    raw_database_url = os.getenv("DATABASE_URL", "").strip()
    return Settings(
        database_url=normalize_database_url(raw_database_url or DEV_DATABASE_URL),
        secret_key=os.getenv("SECRET_KEY", DEV_SECRET_KEY),
        port=int(os.getenv("PORT", "8000")),
        site_name=os.getenv("SITE_NAME", "amazonia"),
        database_url_from_env=bool(raw_database_url),
        cookie_secure_override=env_flag("COOKIE_SECURE"),
    )
