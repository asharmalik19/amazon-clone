"""Database engine and session wiring: one model layer, two backends."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base


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


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    """Return the process-wide session factory, bound to the engine.

    `expire_on_commit` stays off: a route that commits and then renders would otherwise
    re-query every attribute it touches, and a detached object would raise instead.
    """
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session, closed either way.

    Read routes never commit, so nothing is committed here implicitly: a write path
    commits explicitly, which keeps "this request changed data" visible in the route
    rather than hidden in the dependency.
    """
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def create_schema(engine: Engine | None = None) -> None:
    """Create any table that does not exist yet.

    This project has no migration tool: the schema comes from the models and the data
    from the seed. `create_all` is the honest expression of that -- it is a no-op once
    the tables exist, so the seed can run it on every boot, and it is why the seed is
    safe to put in the container's start command.
    """
    Base.metadata.create_all(bind=engine or get_engine())
