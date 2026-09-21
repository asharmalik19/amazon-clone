"""FastAPI application: startup, static files, and template wiring."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from app.config import BASE_DIR, get_settings
from app.db import get_engine

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
    logger.info("database reachable via %s", engine.dialect.name)
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

templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["site_name"] = settings.site_name

# Header controls stay visibly inert until the phase that implements them lands, so the
# shell never shows a control that does nothing. Each flag flips in exactly one phase.
templates.env.globals["features"] = {
    "search": False,  # Phase 6
    "categories": False,  # Phase 7
    "cart": False,  # Phase 8
    "account": False,  # Phase 11
}


@app.get("/healthz")
async def healthz() -> JSONResponse:
    """Liveness probe for the platform health check."""
    return JSONResponse({"status": "ok"})


@app.get("/")
async def home(request: Request):
    """Landing page. The catalog grid arrives in Phase 4; until then, a placeholder."""
    return templates.TemplateResponse(request, "home.html")
