"""The page shell: the category nav, the cart badge and who is signed in.

It lives here rather than in a router because three routers render it -- the catalog
screens, the product detail page and the cart all draw the header bar -- and a router
importing another router to get at its queries is the kind of knot that only tightens.

The list is passed explicitly into each template context rather than injected by a
context processor or middleware. That costs one line per route and buys two things: a
page that has no business showing a category bar (an error page) simply does not get one,
and a test that swaps the database out from under the app through FastAPI's dependency
overrides swaps the nav out with it, instead of quietly reading the real catalog.
"""

from collections.abc import Sequence

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cart import cart_item_count, read_cart
from app.models import Category
from app.security import read_user

# What `nav_active` holds on the landing page. The nav's first link is "All", and on the
# full catalog that link *is* the page the shopper is on, so it carries the same active
# state as a category does on a category page.
NAV_ALL = "all"


def list_categories(db: Session) -> Sequence[Category]:
    """Every category, in the display order the seed file declares.

    Explicit `position` rather than name or id: the header bar should not reorder itself
    because a category was renamed or the seed happened to insert rows in a new order.
    """
    return db.scalars(select(Category).order_by(Category.position, Category.name)).all()


def shell(
    db: Session,
    request: Request,
    *,
    nav_active: str | None = None,
    search_category: Category | None = None,
) -> dict:
    """The context every page's header needs, ready to merge into a template context.

    `nav_active` is the slug of the category whose nav link is the current page, or
    `NAV_ALL` on the full catalog, or `None` on a page that is not a listing at all --
    a product, say, where no nav link is the page being looked at.

    `search_category` scopes the header search box. Set it and the form carries a hidden
    `category` field, so a shopper who is already looking at one shelf searches that
    shelf rather than being thrown back out to the whole catalog.

    `cart_count` is read from the request's cookie, so the badge is already right on a
    plain page load rather than only after an HTMX swap. It is a read and stays one:
    `read_cart` cannot create a cart or a cookie, so drawing the header for a visitor
    who is only browsing writes nothing.

    `current_user` is read the same way, from the session cookie, and is `None` for a
    signed-out visitor. It belongs here rather than in each route because the header
    greets the shopper on every page: one function decides who they are, so no screen can
    show "Hello, sign in" to somebody who is signed in. `read_user` is also a pure read,
    for the same reason `read_cart` is.
    """
    return {
        "categories": list_categories(db),
        "nav_active": nav_active,
        "search_category": search_category,
        "cart_count": cart_item_count(read_cart(db, request)),
        "current_user": read_user(db, request),
    }
