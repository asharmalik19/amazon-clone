"""The shared Jinja2 environment.

Templates live here rather than in `main.py` so that every router renders through the
same environment -- one place where the globals below are true, instead of each router
building an environment that drifts from the others.
"""

from fastapi.templating import Jinja2Templates

from app.cart import MAX_ADD_QUANTITY
from app.config import BASE_DIR, get_settings
from app.nav import NAV_ALL

templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["site_name"] = get_settings().site_name
# The category nav compares its links against `nav_active`; this is the value that
# means "the full catalog", so the template never hard-codes the sentinel.
templates.env.globals["nav_all"] = NAV_ALL
# The quantity picker's ceiling. A global rather than a per-route context value because
# it is the same number on every page that offers the control, and because the limit the
# page offers has to be the limit the route enforces -- both read this one constant.
templates.env.globals["max_add_quantity"] = MAX_ADD_QUANTITY

# Controls stay visibly inert until the phase that implements them lands, so no screen
# ever shows a control that does nothing. Each flag flips in exactly one phase.
templates.env.globals["features"] = {
    "product_detail": True,  # Phase 5
    "search": True,  # Phase 6
    "categories": True,  # Phase 7
    "cart": True,  # Phase 8
    "account": False,  # Phase 11
}
