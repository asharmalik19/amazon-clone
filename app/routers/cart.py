"""The cart: putting something in it, looking at it, and changing your mind about it.

Four routes, and the split between them is the point.

`GET /cart` is a read, so it never creates a cart or sets a cookie -- a shopper who
clicks the header link before adding anything sees the empty state and leaves no trace.

`POST /cart/add` is the only write that may bring a cart into existence, so it is the
only place a `Cart` row and a cookie are created. `POST /cart/update` and
`POST /cart/remove` edit a cart that already exists and never create one: an edit to a
cart nobody has is an edit to nothing, and answering it by creating an empty cart would
fill the table with rows for requests that changed nothing.

Every write route answers twice, from one implementation. An HTMX request gets a
fragment -- the confirmation on the product page, the re-rendered cart region on the
cart page -- and a plain form post gets a 303 to `/cart`. That is not a fallback bolted
on afterwards: it is why each control is a real form with `hx-post` layered over it, per
specs/tech-stack.md, so the write path degrades to a page navigation rather than to a
dead button.

Checkout is not here and never will be; see specs/mission.md. The cart page renders a
visibly disabled button in its place rather than a live control with nothing behind it.
"""

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from app.cart import (
    MAX_ADD_QUANTITY,
    add_to_cart,
    cart_item_count,
    get_or_create_cart,
    parse_quantity,
    read_cart,
    remove_item,
    set_cart_cookie,
    set_quantity,
)
from app.db import DbSession
from app.models import Cart
from app.nav import shell
from app.routers.product import get_product
from app.templating import templates

router = APIRouter()


def _resolve_product(db, slug: str):
    """The product `slug` names, or the same 404 an unknown slug gets everywhere else.

    The slug is never echoed back into the response: it is attacker-supplied text.
    """
    product = get_product(db, slug)
    if product is None:
        raise HTTPException(status_code=404, detail="We could not find that product.")
    return product


def _edited_cart_response(request: Request, cart: Cart | None) -> Response:
    """The answer to an edit: the re-rendered cart region, or a 303 back to the page.

    Both routes answer identically because both change the same things -- a line, the
    two subtotals and the header badge -- so there is one response shape rather than one
    per verb. The HTMX branch returns `fragments/cart_contents.html`, which decides for
    itself whether the cart still has lines; that is what makes "removed the last item"
    render the empty state without a second template or a redirect.

    No cookie is ever set here. An edit either found a cart via the cookie the shopper
    already had, or found nothing to edit.
    """
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(
            request,
            "fragments/cart_contents.html",
            {"cart": cart, "cart_count": cart_item_count(cart)},
        )
    # 303, so the browser follows with a GET and a refresh of the cart page does not
    # replay the edit.
    return RedirectResponse("/cart", status_code=303)


@router.get("/cart")
async def cart_page(request: Request, db: DbSession):
    """Everything in the shopper's cart, with per-line totals, the subtotal and the
    controls that change them.

    A missing, stale or tampered cookie all land here as `cart is None`, which renders
    the same empty state as a genuinely emptied cart. From the shopper's side those are
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
    product = _resolve_product(db, slug)

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


@router.post("/cart/update")
async def update(
    request: Request,
    db: DbSession,
    slug: str = Form(..., description="The product whose line is being changed."),
    quantity: str = Form(..., description="The new quantity, 0 to MAX_ADD_QUANTITY."),
):
    """Set a line's quantity. Zero removes the line.

    Zero is accepted here and refused by `POST /cart/add` -- the same parser with a
    different floor -- because on the cart page zero is a shopper saying "take it out",
    while adding zero of something means nothing at all.
    """
    product = _resolve_product(db, slug)

    parsed = parse_quantity(quantity, minimum=0)
    if parsed is None:
        # Unreachable from the rendered page: the picker offers exactly the values this
        # accepts. So this is a hand-built or replayed request, and it is refused rather
        # than clamped -- guessing at what a malformed quantity meant is how a shopper
        # ends up buying something they did not choose.
        raise HTTPException(
            status_code=400,
            detail=f"Choose a quantity between 0 and {MAX_ADD_QUANTITY}.",
        )

    # A read, not `get_or_create_cart`: editing is not a reason to own a cart.
    cart = read_cart(db, request)
    if cart is not None:
        # A product that is not in this cart is not an error -- see `set_quantity`.
        set_quantity(db, cart, product, parsed)
        db.commit()
    return _edited_cart_response(request, cart)


@router.post("/cart/remove")
async def remove(
    request: Request,
    db: DbSession,
    slug: str = Form(..., description="The product to take out of the cart."),
):
    """Drop a line from the cart.

    Idempotent: pressing Delete twice, or in a stale second tab, removes the line once
    and then finds nothing to remove. Both times the shopper gets the cart as it now
    stands, which is the state they asked for.
    """
    product = _resolve_product(db, slug)

    cart = read_cart(db, request)
    if cart is not None:
        remove_item(db, cart, product)
        db.commit()
    return _edited_cart_response(request, cart)
