"""FastAPI application: startup, static files, and template wiring."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.config import BASE_DIR, get_settings
from app.db import create_schema, get_engine
from app.routers import catalog

# Uvicorn configures its own loggers and leaves the root logger bare, so an application
# log line would otherwise vanish instead of reaching the platform log. This is the
# process entrypoint, so it is the right place to set that up.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(message)s")
logger = logging.getLogger("amazonia")

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Prove the configured database is reachable before serving traffic.

    A container that cannot reach its database is broken, not slow, so it should fail
    the health check immediately rather than boot and serve errors later. This is also
    how the deploy verifies the Postgres wiring while there is still nothing on the
    page worth breaking.
    """
    engine = get_engine()
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    # The seed creates the schema too, and in production it has already run by the time
    # this does. This covers the other case: an app pointed at a fresh database that has
    # never been seeded. Creating the empty tables means the landing page can say "the
    # catalog is empty" instead of failing on a missing table. It is a no-op otherwise.
    create_schema(engine)
    # Say where the URL came from, not just which backend won. "sqlite" alone cannot
    # distinguish "DATABASE_URL is missing" from "DATABASE_URL points at SQLite", which
    # is exactly the question to ask when a deploy looks wrong. The URL itself is never
    # logged -- it carries the database password.
    source = "DATABASE_URL" if settings.database_url_from_env else "the local default"
    logger.info("database reachable via %s, configured from %s", engine.dialect.name, source)
    if not settings.database_url_from_env and settings.is_production:
        logger.warning(
            "DATABASE_URL is not set: running on a container-local SQLite file that this "
            "platform wipes on restart. Anything stored here will be lost."
        )
    yield
    engine.dispose()


app = FastAPI(
    title="amazonia",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(catalog.router)


@app.get("/healthz")
async def healthz() -> JSONResponse:
    """Liveness probe for the platform health check."""
    return JSONResponse({"status": "ok"})
