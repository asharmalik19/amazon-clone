"""FastAPI application: startup, static files, and template wiring."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import BASE_DIR, get_settings

settings = get_settings()

app = FastAPI(title="amazonia", docs_url=None, redoc_url=None, openapi_url=None)
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
