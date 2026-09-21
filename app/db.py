"""Database engine wiring: one model layer, two backends.

Phase 2 owns only the connection -- creating an engine that is correct for both SQLite
and Postgres, so the deployed app boots against managed Postgres. Models, the session
dependency, and schema creation arrive with the data model in Phase 3.
"""

from functools import lru_cache

from sqlalchemy import Engine, create_engine

from app.config import get_settings


def make_engine(database_url: str) -> Engine:
    """Build an engine for `database_url`, applying the per-backend settings it needs."""
    if database_url.startswith("sqlite"):
        # SQLite's default driver rejects a connection used from another thread, which is
        # exactly what a threadpool-backed app does between requests.
        return create_engine(database_url, connect_args={"check_same_thread": False})

    # Render's free tier recycles idle connections; pre-ping trades one cheap round trip
    # for never serving an error from a connection the server has already closed.
    return create_engine(database_url, pool_pre_ping=True, pool_size=5, max_overflow=5)


@lru_cache
def get_engine() -> Engine:
    """Return the process-wide engine, built once from settings."""
    return make_engine(get_settings().database_url)
