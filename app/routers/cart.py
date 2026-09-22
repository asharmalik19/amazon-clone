"""The cart: putting something in it, and looking at what is in it.

Two routes, and the split between them is the point. `GET /cart` is a read, so it never
creates a cart or sets a cookie -- a shopper who clicks the header link before adding
anything sees the empty state and leaves no trace. `POST /cart/add` is the one write in
the phase, so it is the only place a cart row and a cookie come into existence.

The add route answers twice, from one implementation. An HTMX request gets a fragment
and the shopper stays on the product page; a plain form post gets a 303 to `/cart`.
That is not a fallback bolted on afterwards -- it is why the control is a real form with
`hx-post` layered over it, per specs/tech-stack.md: the write path degrades to a page
navigation rather than to a dead button.

Changing a quantity, removing a line and the inert checkout button are Phase 9's. There
is deliberately nothing here that hints at them.
"""

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from app.cart import (
    MAX_ADD_QUANTITY,
    add_to_cart,
    get_or_create_cart,
    parse_quantity,
    read_cart,
    set_cart_cookie,
)
from app.db import DbSession
from app.nav import shell
from app.routers.product import get_product
from app.templating import templates

router = APIRouter()


@router.get("/cart")
async def cart_page(request: Request, db: DbSession):
    """Everything in the shopper's cart, with per-line totals and the subtotal.

    A missing, stale or tampered cookie all land here as `cart is None`, which renders
    the same empty state as a genuinely empty cart. From the shopper's side those are
    the same situation -- there is nothing in the cart -- and the page that says so is
    the honest answer to all of them.
    """
    return templates.TemplateResponse(
        request,
        "cart.html",
        {"cart": read_cart(db, request)}
        # No nav link is highlighted: the cart is not a shelf of the catalog. The search
        # box is left unscoped, because a shopper searching from their cart is starting
        # something new rather than refining where they are.
        | shell(db, request),
    )


@router.post("/cart/add")
async def add(
    request: Request,
    db: DbSession,
    slug: str = Form(..., description="The product to add."),
    # Taken as text and parsed in `parse_quantity`, not declared as an `int`: an `int`
    # parameter would turn a hand-built POST into FastAPI's 422 validation body, and
    # "0" and "-1" would pass that check anyway. One function decides what a quantity
    # is, and it is the same one the picker's ceiling comes from.
    quantity: str = Form("1", description="How many to add, 1 to MAX_ADD_QUANTITY."),
):
    """Add a product to the cart, then say so in whichever way the caller asked for."""
    product = get_product(db, slug)
    if product is None:
        # The same 404 an unknown slug gets on the detail page, and the slug is not
        # echoed back: it is attacker-supplied text.
        raise HTTPException(status_code=404, detail="We could not find that product.")

    parsed = parse_quantity(quantity)
    if parsed is None:
        # Unreachable from the rendered page -- the picker is a `<select>` of exactly
        # the values this accepts -- so this is a hand-built or replayed request. It is
        # refused rather than clamped: guessing at what a malformed quantity meant is
        # how a shopper ends up with something they did not choose. Phase 13 gives the
        # non-404 error surface a styled page; until then this is a bare 400.
        raise HTTPException(
            status_code=400,
            detail=f"Choose a quantity between 1 and {MAX_ADD_QUANTITY}.",
        )

    cart, new_token = get_or_create_cart(db, request)
    item = add_to_cart(db, cart, product, parsed)
    # The dependency never commits, so the write is committed here, where it is visible.
    db.commit()

    if request.headers.get("HX-Request") == "true":
        response: Response = templates.TemplateResponse(
            request,
            "fragments/cart_added.html",
            {"item": item, "cart_count": cart.item_count},
        )
    else:
        # 303 rather than 302: the browser must follow it with a GET, so a shopper who
        # refreshes the cart page afterwards is not re-posting the add.
        response = RedirectResponse("/cart", status_code=303)

    if new_token is not None:
        # Only now, after the commit: a cookie naming a cart that was never written
        # would send the shopper back with a token that resolves to nothing.
        set_cart_cookie(response, new_token)
    return response
