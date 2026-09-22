"""Whose cart is this: the signed cookie, the account, and the moment the two become one.

Everything that knows how a shopper is matched to their basket lives here, so there is
one answer to that question rather than one per route. The rules it enforces:

- **A cart belongs to an account or to a cookie, never to both.** A signed-in shopper's
  cart is found by `user_id`; a stranger's by the opaque `session_token` in their cookie.
  Phase 12 is what makes that true in practice: signing in *consumes* the anonymous cart,
  either by adopting it outright or by folding it into the account's and deleting it, so
  there is never a row with both a user and a live token for a cookie to still find.
- **The cookie is signed, not trusted.** It carries an opaque token and an HMAC of that
  token, keyed by `SECRET_KEY`. A tampered, truncated or forged value is treated as no
  cookie at all -- the shopper gets a fresh empty cart instead of an error page, and
  never someone else's basket. "Any value" means any *bytes*: a cookie header is
  arbitrary bytes decoded one-to-one into a `str`, so the signature check compares bytes
  and there is no input that is neither a match nor a mismatch.
- **The cookie outlives the browser.** It carries a 30-day `Max-Age`, refreshed by every
  add, so a shopper who closes the tab and comes back finds their cart -- which is the
  whole point of keying it to a cookie rather than to a tab.
- **Reads never write.** `read_cart` is safe to call while rendering any page; it cannot
  create a row or set a cookie. Only `get_or_create_cart` (from `POST /cart/add` alone)
  and `merge_anonymous_cart` (from signing in or up) do that. That is what keeps a
  browsing visitor -- or a crawler -- out of the `carts` table entirely, and it is why
  changing or removing a line reads the cart rather than creating one: an edit to a cart
  that does not exist has nothing to edit.

The signing itself lives in `app.security`, which the session cookie uses too: one HMAC
implementation for both cookies, out of the standard library rather than a dependency,
because signing a short opaque token is thirty lines and the alternative is a package in
the image for one call. `read_user` comes from the same module, so "who is signed in" has
one implementation as well -- the header greeting and the cart lookup cannot disagree.
"""

import secrets

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models import Cart, CartItem, Product, User
from app.security import read_user, sign, unsign

# The cookie a shopper's basket is found by.
COOKIE_NAME = "cart_session"

# What the quantity picker offers, and therefore the most one add can put in the cart.
# A line can exceed it by being added to repeatedly -- a shopper who adds ten twice
# wants twenty, and refusing the second add would be a rule invented to be enforced.
MAX_ADD_QUANTITY = 10

# How long an untouched cart stays findable. Long enough that "I'll come back to it
# later" is true, short enough that a shared machine does not hand the next person a
# basket months after the fact. Every add pushes it out again, so the window is thirty
# days of *inactivity*, not thirty days of existence.
COOKIE_MAX_AGE_DAYS = 30
COOKIE_MAX_AGE = COOKIE_MAX_AGE_DAYS * 24 * 60 * 60


def sign_token(token: str) -> str:
    """The cookie value for `token`: the token itself, then its signature."""
    return sign(token)


def read_token(request: Request) -> str | None:
    """The verified token from the request's cookie, or `None` if there isn't a good one.

    `None` covers every failure the same way -- absent, malformed, or signed with a
    different key -- because none of them are distinguishable from the shopper's side
    and none of them should be met with anything other than a fresh cart. In particular
    a rotated `SECRET_KEY` invalidates old cookies rather than crashing on them.

    The verification itself is `app.security.unsign`, which is also what checks the
    session cookie: one HMAC implementation, one reject path, and no way for the two
    cookies to end up disagreeing about what a valid signature is. See that function for
    why the comparison is constant-time and over bytes.
    """
    return unsign(request.cookies.get(COOKIE_NAME))


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

    Account first, cookie second: a signed-in shopper's cart is the one their account
    owns, so it follows them to another browser and survives the cart cookie expiring.
    Only a stranger's cart is looked up by token. The two are asked in that order rather
    than merged here because merging is a write, and this is the function every page
    render calls -- see `merge_anonymous_cart` for where the two actually meet.

    It is a read and stays one, so a visitor who is only browsing leaves no trace, and an
    unknown or tampered token simply looks like an empty-handed visitor rather than an
    error.
    """
    user = read_user(db, request)
    if user is not None:
        return read_user_cart(db, user)
    return read_anonymous_cart(db, request)


def read_anonymous_cart(db: Session, request: Request) -> Cart | None:
    """The cart the request's cart cookie names, or `None`.

    Kept separate from `read_cart` because signing in needs to ask this exact question of
    a request that *is* signed in: the whole job of the merge is to find the basket the
    stranger was carrying a moment ago, which `read_cart` would no longer look for.

    An adopted cart has had its `session_token` cleared, so a cookie left over from
    before a merge matches nothing here rather than handing back a cart the account now
    owns.
    """
    token = read_token(request)
    if token is None:
        return None
    return db.scalars(_cart_query().where(Cart.session_token == token)).one_or_none()


def read_user_cart(db: Session, user: User) -> Cart | None:
    """The cart `user`'s account owns, or `None` if they have never added anything.

    `limit(1)` ordered by id, rather than `one_or_none` over everything the account owns:
    there is no unique index on `carts.user_id` to lean on -- this project has no
    migrations, and `create_all` cannot add a constraint to the table already in
    production -- so two simultaneous sign-ins in two browsers could in principle each
    create a cart for the same account. The oldest one wins, deterministically, instead
    of the read raising `MultipleResultsFound` and turning every page that draws a cart
    badge into a 500. `merge_anonymous_cart` is what keeps the case theoretical: it is
    the only thing that sets `user_id`, and it always folds into the cart it finds here.
    """
    return db.scalars(
        _cart_query().where(Cart.user_id == user.id).order_by(Cart.id).limit(1)
    ).one_or_none()


def get_or_create_cart(db: Session, request: Request) -> tuple[Cart, str | None]:
    """The shopper's cart, creating one if they have none, and the token it is found by.

    The token is `None` for a signed-in shopper, because their cart is not found by a
    cookie at all -- so the caller has no cookie to set, and must not invent one. For a
    stranger it comes back whether or not the cart is new, because the caller sets the
    cookie either way: re-sending it is what pushes `COOKIE_MAX_AGE` out again, so a
    cart in weekly use never expires while a forgotten one does. It is handed back
    rather than written here because only the route holds the response -- and the cookie
    must not be set unless the write it belongs to actually succeeds.

    A token that verifies but names no row -- an anonymous cart consumed by a merge, or a
    database replaced under a still-valid cookie -- issues a new cart under a new token
    instead of failing. "Your cookie is stale" is not a sentence a shopper should ever
    have to read.
    """
    user = read_user(db, request)
    if user is not None:
        cart = read_user_cart(db, user)
        if cart is None:
            cart = Cart(user_id=user.id)
            db.add(cart)
        return cart, None

    cart = read_anonymous_cart(db, request)
    if cart is not None:
        return cart, cart.session_token

    token = new_token()
    cart = Cart(session_token=token)
    db.add(cart)
    return cart, token


def set_cart_cookie(response: Response, token: str) -> None:
    """Attach the signed cart cookie for `token` to `response`.

    `httponly` because no script needs to read it and a stolen token is a stolen cart.
    `samesite="lax"` so the cookie still travels when a shopper follows a link in from
    somewhere else, but not on a cross-site POST.

    `max_age` is what makes a cart survive the tab being closed: without it the browser
    keeps the cookie only for the session, and "come back tomorrow and your cart is
    there" is false. With it, the cart outlives the browser but not the month.

    `secure` comes from the settings rather than from the request, for the reason
    `Settings.cookie_secure` explains. It has to be conditional either way: a `Secure`
    cookie on a local HTTP server is dropped by the browser silently, which looks
    exactly like a cart that does not work and leaves nothing in the log.
    """
    response.set_cookie(
        COOKIE_NAME,
        sign_token(token),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_cart_cookie(response: Response) -> None:
    """Drop the cart cookie from the browser.

    Called when signing in has consumed the anonymous cart: the token it carried now
    names either nothing or a row the account owns under a cleared token, so leaving the
    cookie in place would leave the browser holding a key to a door that is gone. The
    signed-in shopper's cart is found by their account from here on.

    The attributes are repeated because a cookie is deleted by being overwritten: a
    browser only replaces a cookie whose name, path and domain match, so "expire it" has
    to be sent with the same `path` it was set with or the old one simply stays. It is the
    same shape `app.security.clear_session` uses for the session cookie.
    """
    response.delete_cookie(
        COOKIE_NAME,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        path="/",
    )


def merge_anonymous_cart(db: Session, request: Request, user: User) -> Cart | None:
    """Fold the cart `request` was carrying anonymously into `user`'s, and return theirs.

    This is the whole of Phase 12, and it runs on exactly two paths -- signing in and
    signing up -- because those are the two moments a stranger becomes an account. The
    caller commits, and only then drops the cart cookie: the token must not stop working
    before the row it names has actually moved.

    There are three cases and each one is the obvious thing:

    - **No anonymous cart.** Nothing to merge; the account's own cart (or `None`) is
      already the answer. A shopper who signs in on a fresh browser is this case.
    - **An anonymous cart and no account cart.** The cart is *adopted* rather than copied:
      `user_id` is set and `session_token` cleared, so the line ids, their order and the
      cart's age all survive, and no row is written twice. Clearing the token is what
      keeps the invariant in this module's docstring true -- a cart is never findable by
      both an account and a cookie.
    - **Both.** Each anonymous line goes through `add_to_cart`, which is the same summing
      the unique constraint on `(cart_id, product_id)` demands, so a product in both
      carts ends up on one line with the quantities added rather than twice at two
      prices. The emptied anonymous cart is then deleted -- `delete-orphan` takes its
      lines with it -- because a row nothing can reach is a row that should not exist.

    A merged line may exceed `MAX_ADD_QUANTITY`, and that is correct: ten in the account
    plus ten in the browser is a shopper who wants twenty, and the cart page's picker
    already renders a quantity above its ceiling rather than quietly clamping it. The
    limit bounds one add, not what a cart may hold.
    """
    anonymous = read_anonymous_cart(db, request)
    existing = read_user_cart(db, user)

    if anonymous is None:
        return existing

    if existing is None:
        anonymous.user_id = user.id
        anonymous.session_token = None
        db.flush()
        return anonymous

    for item in list(anonymous.items):
        add_to_cart(db, existing, item.product, item.quantity)
    db.delete(anonymous)
    db.flush()
    return existing


def add_to_cart(db: Session, cart: Cart, product: Product, quantity: int) -> CartItem:
    """Put `quantity` of `product` into `cart`, summing onto the line if it is there.

    Summing rather than appending is what makes the unique constraint on
    `(cart_id, product_id)` true in practice: a shopper who adds the same thing twice
    has one line of two, not two lines of one.

    The caller commits. `db.flush()` here assigns the new cart its id -- the line needs
    it -- without deciding for the route whether the request as a whole succeeded.
    """
    db.flush()
    existing = find_item(cart, product)
    if existing is not None:
        existing.quantity += quantity
        return existing

    item = CartItem(cart_id=cart.id, product_id=product.id, quantity=quantity)
    cart.items.append(item)
    return item


def find_item(cart: Cart, product: Product) -> CartItem | None:
    """The line `product` is on in `cart`, or `None` if it is not in the cart.

    One matcher for all three write paths -- add, update, remove -- because the unique
    constraint on `(cart_id, product_id)` guarantees there is at most one line to find,
    and three hand-rolled searches would be three places for that guarantee to be
    forgotten. The scan is over the lines already loaded with the cart, so it costs no
    query.
    """
    return next((item for item in cart.items if item.product_id == product.id), None)


def set_quantity(db: Session, cart: Cart, product: Product, quantity: int) -> CartItem | None:
    """Set `product`'s line in `cart` to `quantity`, or remove it when `quantity` is 0.

    Returns the line, or `None` when there is no longer one -- removed, or never there.

    A quantity of zero is a removal rather than a stored zero: `CheckConstraint
    ("quantity >= 1")` would refuse the row anyway, and a shopper who picks 0 has said
    "take it out", not "keep a line worth nothing".

    Removal goes through `cart.items.remove`, not `db.delete`, so the `delete-orphan`
    cascade deletes the row *and* the in-memory cart the caller is about to render is
    already correct. Deleting the object alone would leave the removed line in
    `cart.items` until a refresh, and the subtotal in the response would still include
    it.

    A product that is not in the cart is not an error. A double-submitted Delete, a
    stale second tab and a cleared cookie all arrive here as "that line is already
    gone", which is the state the shopper asked for.
    """
    item = find_item(cart, product)
    if item is None:
        return None
    if quantity == 0:
        cart.items.remove(item)
        db.flush()
        return None
    item.quantity = quantity
    return item


def remove_item(db: Session, cart: Cart, product: Product) -> bool:
    """Drop `product`'s line from `cart`. `True` if there was one to drop.

    The same operation the picker's `0` performs, kept as its own function because it is
    its own control: a shopper reaching for Delete should not have to route their intent
    through a quantity. `False` means there was nothing to remove, which is a fine
    outcome for a Delete pressed twice -- the caller renders the cart either way.
    """
    item = find_item(cart, product)
    if item is None:
        return False
    cart.items.remove(item)
    db.flush()
    return True


def parse_quantity(raw: str, *, minimum: int = 1) -> int | None:
    """`raw` as a quantity between `minimum` and `MAX_ADD_QUANTITY`, or `None`.

    The picker is a `<select>` of exactly these values, so a shopper cannot produce
    anything else: a rejected quantity means a hand-built or replayed POST, not a
    mistake. It is still checked here rather than declared as an `int` parameter,
    because the route wants to answer with its own status rather than a framework
    validation error -- and because "0" and "-1" are integers that parse fine and still
    must not reach the database.

    `minimum` is the one thing the two write paths disagree about. Adding zero of
    something is meaningless, so `POST /cart/add` keeps the default floor of 1; on the
    cart page `0` is how a shopper deletes a line, so `POST /cart/update` passes
    `minimum=0`. The ceiling is the same number for both, and it is the same number the
    picker is built from.
    """
    try:
        quantity = int(raw)
    except (TypeError, ValueError):
        return None
    if not minimum <= quantity <= MAX_ADD_QUANTITY:
        return None
    return quantity


def cart_item_count(cart: Cart | None) -> int:
    """How many units are in `cart` -- zero for a visitor who has no cart at all."""
    return cart.item_count if cart is not None else 0
