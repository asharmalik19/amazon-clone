"""The shared Jinja2 environment.

Templates live here rather than in `main.py` so that every router renders through the
same environment -- one place where the globals below are true, instead of each router
building an environment that drifts from the others.
"""

from fastapi.templating import Jinja2Templates

from app.config import BASE_DIR, get_settings

templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["site_name"] = get_settings().site_name

# Controls stay visibly inert until the phase that implements them lands, so no screen
# ever shows a control that does nothing. Each flag flips in exactly one phase.
templates.env.globals["features"] = {
    "product_detail": False,  # Phase 5
    "search": False,  # Phase 6
    "categories": False,  # Phase 7
    "cart": False,  # Phase 8
    "account": False,  # Phase 11
}
