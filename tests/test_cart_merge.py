"""Phase 12: the cart and the account meet, and nothing is lost or doubled.

The roadmap's acceptance is one sentence -- "add items while signed out, sign in, and
nothing is lost or doubled" -- and the word doing the work is *doubled*. A merge that
appends is as broken as one that drops: a shopper who had two of something in their
account and one in their browser must end up with three on one line, not with two lines
or with one of them gone.

So the assertions here are mostly arithmetic, read back off the rendered cart page rather
than out of the database, because the subtotal and the quantity picker are what a shopper
actually checks. The four questions:

1. **Nothing is lost.** Anonymous lines survive signing in, and survive signing up too --
   filling a cart and then creating an account is the likeliest order a stranger does
   this in.
2. **Nothing is doubled.** A product in both carts ends up on one line with the
   quantities summed, and the subtotal agrees.
3. **The cart is the account's afterwards.** Sign out and back in and it is still there;
   sign out and it is *not* in the browser, because it went with the account. Another
   account never sees it.
4. **The anonymous cart is consumed, not copied.** The cart cookie is dropped on the way
   in, the row it named is gone or re-owned, and a signed-in add never sets a cart cookie
   at all -- otherwise there would be two live answers to whose cart this is.

Every test drives the real endpoints with one cookie jar, so what is under test is what a
browser would actually do.
"""

import re

from sqlalchemy import select

from app.cart import COOKIE_NAME as CART_COOKIE
from app.db import get_sessionmaker
from app.models import Cart
from app.security import unsign
from tests.auth_helpers import an_email, signin, signout, signup
from tests.cart_helpers import add, cart_page, line_slugs, line_totals, money, quantity_of, remove


def two_products(catalog) -> tuple[dict, dict]:
    """Two distinct seeded products, so "summed" can be told apart from "appended"."""
    return catalog["products"][0], catalog["products"][1]


def carts_for_token(token: str) -> list[Cart]:
    """Every cart row still findable by `token`, read outside the app's own session."""
    session = get_sessionmaker()()
    try:
        return list(session.scalars(select(Cart).where(Cart.session_token == token)))
    finally:
        session.close()


def header_count(client) -> int:
    """What the header badge claims is in the cart, from a plain page load.

    Read off the link's accessible name rather than the badge digits, because that string
    is what a shopper using a screen reader is actually told.
    """
    match = re.search(r"Cart, (\d+) items?", client.get("/").text)
    assert match is not None, "the header rendered no cart count at all"
    return int(match.group(1))


# --- nothing is lost ------------------------------------------------------------------


def test_an_anonymous_cart_follows_the_shopper_into_their_account(client, account, catalog):
    """The roadmap's acceptance: fill a cart as a stranger, sign in, still have it."""
    first, second = two_products(catalog)
    add(client, first["slug"], quantity=2)
    add(client, second["slug"])

    assert signin(client, account).status_code == 303

    page = cart_page(client)
    assert line_slugs(page) == [first["slug"], second["slug"]]
    assert quantity_of(page, first["slug"]) == 2
    assert quantity_of(page, second["slug"]) == 1
    assert line_totals(page)[-1] == money(first["price_cents"] * 2 + second["price_cents"])


def test_a_new_account_keeps_the_cart_it_was_created_from(client, catalog):
    """Signing up merges too -- a shopper fills a cart and *then* decides to register."""
    product = catalog["products"][0]
    add(client, product["slug"], quantity=3)

    assert signup(client).status_code == 303

    page = cart_page(client)
    assert quantity_of(page, product["slug"]) == 3
    assert header_count(client) == 3


def test_signing_in_with_an_empty_browser_keeps_the_accounts_cart(client, account, catalog):
    """No anonymous cart to merge is not a reason to lose the one the account has."""
    product = catalog["products"][0]
    signin(client, account)
    add(client, product["slug"], quantity=2)
    signout(client)
    client.cookies.clear()

    assert signin(client, account).status_code == 303
    assert quantity_of(cart_page(client), product["slug"]) == 2


# --- nothing is doubled ---------------------------------------------------------------


def test_a_product_in_both_carts_ends_up_on_one_line(client, account, catalog):
    """The same product from both sides is summed once, not listed twice."""
    product = catalog["products"][0]

    signin(client, account)
    add(client, product["slug"], quantity=2)
    signout(client)
    client.cookies.clear()

    add(client, product["slug"], quantity=3)
    signin(client, account)

    page = cart_page(client)
    assert line_slugs(page) == [product["slug"]]
    assert quantity_of(page, product["slug"]) == 5
    assert line_totals(page)[-1] == money(product["price_cents"] * 5)
    assert header_count(client) == 5


def test_overlapping_and_new_products_merge_side_by_side(client, account, catalog):
    """One product in both carts, one in each: three lines' worth of stock, three lines."""
    first, second = two_products(catalog)
    third = catalog["products"][2]

    signin(client, account)
    add(client, first["slug"], quantity=2)
    add(client, second["slug"])
    signout(client)
    client.cookies.clear()

    add(client, first["slug"])
    add(client, third["slug"], quantity=4)
    signin(client, account)

    page = cart_page(client)
    assert sorted(line_slugs(page)) == sorted([first["slug"], second["slug"], third["slug"]])
    assert quantity_of(page, first["slug"]) == 3
    assert quantity_of(page, second["slug"]) == 1
    assert quantity_of(page, third["slug"]) == 4
    assert line_totals(page)[-1] == money(
        first["price_cents"] * 3 + second["price_cents"] + third["price_cents"] * 4
    )


def test_a_merged_line_may_exceed_what_one_add_allows(client, account, catalog):
    """Ten in the account plus ten in the browser is twenty, shown as twenty."""
    product = catalog["products"][0]

    signin(client, account)
    add(client, product["slug"], quantity=10)
    signout(client)
    client.cookies.clear()

    add(client, product["slug"], quantity=10)
    signin(client, account)

    page = cart_page(client)
    # The picker appends a selected value above its ceiling rather than clamping it, so
    # the number the shopper reads is the number the cart holds.
    assert quantity_of(page, product["slug"]) == 20
    assert line_totals(page)[-1] == money(product["price_cents"] * 20)


# --- the cart is the account's afterwards ---------------------------------------------


def test_the_cart_is_still_there_the_next_time_they_sign_in(client, account, catalog):
    """signin -> signout -> signin returns the same cart, as the roadmap asks."""
    first, second = two_products(catalog)
    add(client, first["slug"], quantity=2)
    signin(client, account)
    add(client, second["slug"])
    before = cart_page(client)

    assert signout(client).status_code == 303
    assert signin(client, account).status_code == 303

    after = cart_page(client)
    assert line_slugs(after) == line_slugs(before)
    assert quantity_of(after, first["slug"]) == 2
    assert quantity_of(after, second["slug"]) == 1
    assert line_totals(after)[-1] == line_totals(before)[-1]


def test_signing_out_leaves_the_cart_with_the_account(client, account, catalog):
    """The browser goes back to being a stranger's, and a stranger's cart is empty."""
    product = catalog["products"][0]
    add(client, product["slug"])
    signin(client, account)

    assert signout(client).status_code == 303

    assert product["title"] not in cart_page(client)
    assert header_count(client) == 0


def test_one_accounts_cart_is_never_another_accounts(client, catalog):
    """Two accounts on one machine keep two carts."""
    first, second = two_products(catalog)

    assert signup(client).status_code == 303
    add(client, first["slug"])
    signout(client)
    client.cookies.clear()

    assert signup(client, email=an_email()).status_code == 303
    add(client, second["slug"], quantity=2)

    page = cart_page(client)
    assert line_slugs(page) == [second["slug"]]
    assert first["title"] not in page


def test_a_signed_in_cart_survives_losing_the_cart_cookie(client, account, catalog):
    """Found by the account, not by the browser: clearing the cart cookie changes nothing."""
    product = catalog["products"][0]
    signin(client, account)
    add(client, product["slug"], quantity=2)

    assert CART_COOKIE not in client.cookies, "a signed-in add should set no cart cookie"

    assert quantity_of(cart_page(client), product["slug"]) == 2


def test_editing_works_on_the_merged_cart(client, account, catalog):
    """A merged line is an ordinary line: it can be changed and removed like any other."""
    product = catalog["products"][0]
    add(client, product["slug"], quantity=2)
    signin(client, account)

    assert remove(client, product["slug"]).status_code == 303
    assert line_slugs(cart_page(client)) == []
    assert header_count(client) == 0


# --- the anonymous cart is consumed, not copied ---------------------------------------


def test_signing_in_drops_the_cart_cookie(client, account, catalog):
    """The token is spent: the browser is not left holding a key to a re-owned cart."""
    add(client, catalog["products"][0]["slug"])
    token = client.cookies[CART_COOKIE]

    response = signin(client, account)

    assert any(
        header.startswith(f"{CART_COOKIE}=") for header in response.headers.get_list("set-cookie")
    ), "signing in did not touch the cart cookie"
    assert CART_COOKIE not in client.cookies
    # And the value it held no longer reaches anything, even if a browser kept it.
    client.cookies.set(CART_COOKIE, token)
    signout(client)
    assert line_slugs(cart_page(client)) == []


def test_the_anonymous_cart_row_does_not_outlive_the_merge(client, account, catalog):
    """Adopted or emptied and deleted -- either way, no row is left behind by its token."""
    product = catalog["products"][0]
    signin(client, account)
    add(client, product["slug"])
    signout(client)
    client.cookies.clear()

    add(client, product["slug"])
    token = unsign(client.cookies[CART_COOKIE])
    assert carts_for_token(token), "the anonymous add wrote no cart to merge"

    signin(client, account)

    assert carts_for_token(token) == []


def test_a_signed_in_add_sets_no_cart_cookie(client, account, catalog):
    """One answer to whose cart this is: the account, with no cookie competing."""
    signin(client, account)

    response = add(client, catalog["products"][0]["slug"])

    assert response.status_code == 303
    assert not [
        header
        for header in response.headers.get_list("set-cookie")
        if header.startswith(f"{CART_COOKIE}=")
    ]
    assert CART_COOKIE not in client.cookies
