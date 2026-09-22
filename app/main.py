"""FastAPI application: startup, static files, and template wiring."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import BASE_DIR, get_settings
from app.db import create_schema, get_engine
from app.routers import catalog, product
from app.templating import templates

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
app.include_router(product.router)


# FastAPI's default 404 is a JSON body, which is the wrong answer for a storefront a
# person is browsing: a shopper who follows a stale link should land on the site, not on
# `{"detail":"Not Found"}`. Phase 13 extends this to the rest of the error surface; the
# 404 arrives now because an unknown product slug is a state Phase 5 has to handle.
@app.exception_handler(StarletteHTTPException)
async def not_found_page(request: Request, exc: StarletteHTTPException) -> Response:
    """Render 404s as a page; leave every other status to FastAPI's own handler."""
    if exc.status_code != 404:
        return await http_exception_handler(request, exc)
    # Starlette's own default detail is the bare reason phrase. A route that raised a
    # sentence of its own gets to keep it; anything else gets copy written for a person.
    message = exc.detail
    if not message or message == "Not Found":
        message = "We could not find that page."
    return templates.TemplateResponse(
        request, "not_found.html", {"message": message}, status_code=404
    )


@app.get("/healthz")
async def healthz() -> JSONResponse:
    """Liveness probe for the platform health check."""
    return JSONResponse({"status": "ok"})
