"""The anonymous cart's identity: one signed cookie, and the lookups that read it.

Everything that knows how a shopper is matched to their basket lives here, so there is
one answer to "whose cart is this?" rather than one per route. The rules it enforces:

- **The cookie is signed, not trusted.** It carries an opaque token and an HMAC of that
  token, keyed by `SECRET_KEY`. A tampered, truncated or forged value is treated as no
  cookie at all -- the shopper gets a fresh empty cart instead of an error page, and
  never someone else's basket.
- **Reads never write.** `read_cart` is safe to call while rendering any page; it cannot
  create a row or set a cookie. Only `get_or_create_cart`, called from the one write
  route, does that. That is what keeps a browsing visitor -- or a crawler -- out of the
  `carts` table entirely.

The signature uses `hmac` from the standard library rather than a dependency: signing a
short opaque token is thirty lines of stdlib, and the alternative is a package in the
image for one call. Cookie *hardening* -- the `Secure` flag, an explicit lifetime -- is
Phase 10's, and nothing here stands in its way.
"""

import base64
import hashlib
import hmac
import secrets

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models import Cart, CartItem, Product

# The cookie a shopper's basket is found by.
COOKIE_NAME = "cart_session"

# What the quantity picker offers, and therefore the most one add can put in the cart.
# A line can exceed it by being added to repeatedly -- a shopper who adds ten twice
# wants twenty, and refusing the second add would be a rule invented to be enforced.
MAX_ADD_QUANTITY = 10

_SEPARATOR = "."


def _signature(token: str) -> str:
    """The HMAC of `token`, keyed by the application secret, as url-safe base64.

    Truncated padding is stripped so the cookie value stays free of `=`, which would
    otherwise have to be quoted.
    """
    digest = hmac.new(
        get_settings().secret_key.encode("utf-8"), token.encode("utf-8"), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def sign_token(token: str) -> str:
    """The cookie value for `token`: the token itself, then its signature."""
    return f"{token}{_SEPARATOR}{_signature(token)}"


def read_token(request: Request) -> str | None:
    """The verified token from the request's cookie, or `None` if there isn't a good one.

    `None` covers every failure the same way -- absent, malformed, or signed with a
    different key -- because none of them are distinguishable from the shopper's side
    and none of them should be met with anything other than a fresh cart. In particular
    a rotated `SECRET_KEY` invalidates old cookies rather than crashing on them.

    `compare_digest` rather than `==`: the comparison is against attacker-supplied text,
    and a timing difference is the one thing that would make forging a signature easier
    than guessing it.
    """
    value = request.cookies.get(COOKIE_NAME)
    if not value or _SEPARATOR not in value:
        return None
    token, _, signature = value.rpartition(_SEPARATOR)
    if not token or not hmac.compare_digest(signature, _signature(token)):
        return None
    return token


def new_token() -> str:
    """A fresh, unguessable cart token.

    Opaque and random rather than derived from anything: the token is the only thing
    standing between a stranger and an anonymous cart, so it carries no information and
    cannot be enumerated.
    """
    return secrets.token_urlsafe(24)


def _cart_query():
    """A cart with its lines, their products and those products' images loaded.

    The cart page renders a product image and price per line, so lazy relationships
    would turn one page into a query per line. Loading them here means every caller --
    the page and the header badge alike -- gets a cart it can render without going back
    to the database.
    """
    return select(Cart).options(
        selectinload(Cart.items).selectinload(CartItem.product).selectinload(Product.images),
        selectinload(Cart.items).selectinload(CartItem.product).selectinload(Product.category),
    )


def read_cart(db: Session, request: Request) -> Cart | None:
    """The shopper's existing cart, or `None`. Never creates anything.

    This is what every page render calls: it is a read, so a visitor who is only
    browsing leaves no trace, and an unknown or tampered token simply looks like an
    empty-handed visitor rather than an error.
    """
    token = read_token(request)
    if token is None:
        return None
    return db.scalars(_cart_query().where(Cart.session_token == token)).one_or_none()


def get_or_create_cart(db: Session, request: Request) -> tuple[Cart, str | None]:
    """The shopper's cart, creating one if they have none.

    Returns the cart and, when a new one was made, the token whose cookie the caller
    must set with `set_cart_cookie`. The token is handed back rather than written here
    because only the route holds the response -- and the cookie must not be set unless
    the write it belongs to actually succeeds.

    A token that verifies but names no row -- a cart deleted by a later phase's merge,
    or a database replaced under a still-valid cookie -- issues a new cart under a new
    token instead of failing. Phase 10 tests that case as a first-class state; it is
    handled here from the start because "your cookie is stale" is not a sentence a
    shopper should ever have to read.
    """
    cart = read_cart(db, request)
    if cart is not None:
        return cart, None

    token = new_token()
    cart = Cart(session_token=token)
    db.add(cart)
    return cart, token


def set_cart_cookie(response: Response, token: str) -> None:
    """Attach the signed cart cookie for `token` to `response`.

    `httponly` because no script needs to read it and a stolen token is a stolen cart.
    `samesite="lax"` so the cookie still travels when a shopper follows a link in from
    somewhere else, but not on a cross-site POST. The `Secure` flag and an explicit
    lifetime are Phase 10's; until then this is a session cookie, which is enough to
    survive the navigation and refresh Phase 8 promises.
    """
    response.set_cookie(
        COOKIE_NAME,
        sign_token(token),
        httponly=True,
        samesite="lax",
        path="/",
    )


def add_to_cart(db: Session, cart: Cart, product: Product, quantity: int) -> CartItem:
    """Put `quantity` of `product` into `cart`, summing onto the line if it is there.

    Summing rather than appending is what makes the unique constraint on
    `(cart_id, product_id)` true in practice: a shopper who adds the same thing twice
    has one line of two, not two lines of one.

    The caller commits. `db.flush()` here assigns the new cart its id -- the line needs
    it -- without deciding for the route whether the request as a whole succeeded.
    """
    db.flush()
    existing = next((item for item in cart.items if item.product_id == product.id), None)
    if existing is not None:
        existing.quantity += quantity
        return existing

    item = CartItem(cart_id=cart.id, product_id=product.id, quantity=quantity)
    cart.items.append(item)
    return item


def parse_quantity(raw: str) -> int | None:
    """`raw` as a quantity between 1 and `MAX_ADD_QUANTITY`, or `None` if it is not one.

    The picker is a `<select>` of exactly these values, so a shopper cannot produce
    anything else: a rejected quantity means a hand-built or replayed POST, not a
    mistake. It is still checked here rather than declared as an `int` parameter,
    because the route wants to answer with its own status rather than a framework
    validation error -- and because "0" and "-1" are integers that parse fine and still
    must not reach the database.
    """
    try:
        quantity = int(raw)
    except (TypeError, ValueError):
        return None
    if not 1 <= quantity <= MAX_ADD_QUANTITY:
        return None
    return quantity


def cart_item_count(cart: Cart | None) -> int:
    """How many units are in `cart` -- zero for a visitor who has no cart at all."""
    return cart.item_count if cart is not None else 0
