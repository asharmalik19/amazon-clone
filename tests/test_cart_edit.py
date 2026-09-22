"""Phase 9: changing a quantity, removing a line, and the subtotal keeping up.

Like the Phase 8 tests these go through the HTTP surface, because what the phase
promises is a shopper editing their cart -- pick a new quantity, press Update, read the
new subtotal -- and the cookie, the form encoding and the rendered markup are all part
of whether that works.

Every money assertion is computed as `price_cents * quantity` in Python integers and
compared against the string the page renders, so a float creeping into the arithmetic
would show up as a failing comparison rather than as a rounding error nobody notices.
"""

import pytest

from app.cart import COOKIE_NAME, MAX_ADD_QUANTITY, sign_token
from tests.cart_helpers import (
    add,
    cart_page,
    line_slugs,
    line_totals,
    money,
    quantity_of,
    remove,
    update,
)


@pytest.fixture
def products(catalog) -> list[dict]:
    """Two different products from the committed catalog."""
    return catalog["products"][:2]


@pytest.fixture
def product(products) -> dict:
    return products[0]


@pytest.fixture(params=["update", "remove"])
def edit(request):
    """Either edit route, called the same way: `edit(client, slug)`.

    The two routes share a validation path, a cart lookup and a response shape, so the
    cases below -- unknown slug, no cart, tampered cookie, a product that is not in the
    cart -- are the same cases for both. Parametrising the *route* rather than copying
    the test is what keeps them from drifting apart. The quantity the update variant
    posts is arbitrary: these tests assert that nothing changed.
    """
    if request.param == "update":
        return lambda client, slug: update(client, slug, 3)
    return remove


@pytest.fixture
def filled(client, products) -> list[dict]:
    """A cart holding both products: the first ×1, the second ×2."""
    add(client, products[0]["slug"], 1)
    add(client, products[1]["slug"], 2)
    return products


# --- changing a quantity ------------------------------------------------------------


def test_update_sets_the_quantity_and_the_line_total(client, product):
    add(client, product["slug"], 1)
    assert update(client, product["slug"], 4).status_code == 303

    page = cart_page(client)
    assert quantity_of(page, product["slug"]) == 4
    assert money(product["price_cents"] * 4) in page


def test_update_recomputes_the_subtotal(client, filled):
    first, second = filled
    update(client, first["slug"], 3)

    page = cart_page(client)
    expected = first["price_cents"] * 3 + second["price_cents"] * 2
    # Stated twice -- beside the list and in the panel -- and both must be that number.
    assert line_totals(page).count(money(expected)) == 2
    assert "Subtotal (5 items):" in page


def test_update_moves_the_header_badge(client, product):
    add(client, product["slug"], 1)
    update(client, product["slug"], 6)
    assert "Cart, 6 items" in client.get("/").text


def test_update_leaves_the_other_lines_alone(client, filled):
    first, second = filled
    update(client, first["slug"], 5)

    page = cart_page(client)
    assert quantity_of(page, second["slug"]) == 2
    assert money(second["price_cents"] * 2) in page


def test_update_to_zero_removes_the_line(client, filled):
    first, second = filled
    assert update(client, first["slug"], 0).status_code == 303

    page = cart_page(client)
    assert line_slugs(page) == [second["slug"]]
    assert first["title"] not in page
    assert line_totals(page).count(money(second["price_cents"] * 2)) == 3  # line + 2 subtotals


def test_the_picker_offers_zero_and_the_route_accepts_it(client, product):
    """One constant behind both, so the control cannot offer a value that would 400."""
    add(client, product["slug"], 1)
    page = cart_page(client)
    for value in range(0, MAX_ADD_QUANTITY + 1):
        assert f'<option value="{value}"' in page
    assert f'<option value="{MAX_ADD_QUANTITY + 1}"' not in page
    assert "0 (Delete)" in page


def test_the_picker_shows_a_quantity_above_the_ceiling_rather_than_clamping_it(client, product):
    """Repeated adds can legitimately exceed the picker's ceiling; the cart must say so."""
    for _ in range(3):
        add(client, product["slug"], MAX_ADD_QUANTITY)

    page = cart_page(client)
    over = MAX_ADD_QUANTITY * 3
    assert quantity_of(page, product["slug"]) == over
    assert f'<option value="{over}" selected>' in page
    assert money(product["price_cents"] * over) in page


# --- removing a line ----------------------------------------------------------------


def test_remove_drops_that_line_and_keeps_the_rest(client, filled):
    first, second = filled
    assert remove(client, first["slug"]).status_code == 303

    page = cart_page(client)
    assert line_slugs(page) == [second["slug"]]
    assert "Subtotal (2 items):" in page


def test_removing_the_last_line_leaves_the_empty_state(client, product):
    add(client, product["slug"], 2)
    remove(client, product["slug"])

    page = cart_page(client)
    assert "Your cart is empty" in page
    assert 'href="/"' in page
    # Not a bare heading over nothing: the filled cart's furniture is gone with it.
    assert "Subtotal (" not in page
    # The badge goes back to reading 0, which is what it says for any shopper whose
    # cart is empty -- an emptied cart is not a distinct state from a never-filled one.
    assert "Cart, 0 items" in client.get("/").text


def test_removing_twice_is_not_an_error(client, product):
    """A double-submitted Delete, or a stale second tab: the line is already gone."""
    add(client, product["slug"], 1)
    assert remove(client, product["slug"]).status_code == 303
    assert remove(client, product["slug"]).status_code == 303
    assert "Your cart is empty" in cart_page(client)


def test_removing_the_last_line_keeps_the_cart_usable(client, product):
    """Emptying a cart must not orphan the cookie: the next add goes back into it."""
    add(client, product["slug"], 1)
    cookie = client.cookies[COOKIE_NAME]
    remove(client, product["slug"])

    response = add(client, product["slug"], 2)
    # The same cookie back, not a new one: emptying a cart does not abandon it. Phase 10
    # re-sends it on every add to refresh the expiry, so the value is what is asserted
    # here rather than the absence of the header.
    assert response.headers["set-cookie"].startswith(f"{COOKIE_NAME}={cookie};")
    assert client.cookies[COOKIE_NAME] == cookie
    assert quantity_of(cart_page(client), product["slug"]) == 2


# --- requests the rendered page cannot produce --------------------------------------


@pytest.mark.parametrize("bogus", ["-1", "abc", "1.5", "1e1", "", str(MAX_ADD_QUANTITY + 1)])
def test_a_quantity_the_picker_cannot_produce_is_refused(client, product, bogus):
    add(client, product["slug"], 2)
    assert update(client, product["slug"], bogus).status_code == 400
    # Refused rather than clamped, and nothing changed on the way to failing.
    assert quantity_of(cart_page(client), product["slug"]) == 2


def test_an_unknown_slug_is_a_404_and_is_not_echoed_back(client, product, edit):
    add(client, product["slug"], 2)
    response = edit(client, "<script>alert(1)</script>")
    assert response.status_code == 404
    assert "<script>alert" not in response.text
    assert quantity_of(cart_page(client), product["slug"]) == 2


def test_editing_a_product_that_is_not_in_the_cart_changes_nothing(client, products, edit):
    in_cart, not_in_cart = products
    add(client, in_cart["slug"], 2)

    response = edit(client, not_in_cart["slug"])
    # Not an error: the shopper's line is already in the state they asked for.
    assert response.status_code == 303
    page = cart_page(client)
    assert line_slugs(page) == [in_cart["slug"]]
    assert quantity_of(page, in_cart["slug"]) == 2


def test_editing_without_a_cart_creates_neither_a_cart_nor_a_cookie(client, product, edit):
    """Only add-to-cart may bring a cart into existence; an edit has nothing to edit."""
    response = edit(client, product["slug"])
    assert response.status_code == 303
    assert "set-cookie" not in response.headers
    assert not client.cookies
    assert "Your cart is empty" in cart_page(client)


def test_editing_with_a_tampered_cookie_is_treated_as_having_no_cart(client, product, edit):
    add(client, product["slug"], 2)
    client.cookies.set(COOKIE_NAME, "token.wrong-signature")

    response = edit(client, product["slug"])
    assert response.status_code == 303
    assert "Your cart is empty" in cart_page(client)


def test_editing_with_a_stale_but_signed_cookie_does_not_create_a_cart(client, product):
    client.cookies.set(COOKIE_NAME, sign_token("a-token-no-cart-was-ever-saved-under"))
    response = update(client, product["slug"], 3)
    assert response.status_code == 303
    assert "set-cookie" not in response.headers


# --- the two ways an edit answers ---------------------------------------------------


@pytest.mark.parametrize("path", ["/cart/update", "/cart/remove"])
def test_a_plain_form_post_redirects_back_to_the_cart(client, product, path):
    """The no-JavaScript path: the browser posts the form and follows a 303 to /cart."""
    add(client, product["slug"], 2)
    response = client.post(
        path, data={"slug": product["slug"], "quantity": "3"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/cart"


def test_an_htmx_update_gets_the_cart_region_and_the_badge(client, product):
    add(client, product["slug"], 1)
    response = update(client, product["slug"], 4, htmx=True)

    assert response.status_code == 200
    body = response.text
    assert "<!DOCTYPE html>" not in body
    assert 'id="cart-contents"' in body
    # The header badge rides along out of band, so one response updates both places.
    assert 'id="cart-count" hx-swap-oob="true"' in body
    assert '<option value="4" selected>' in body
    assert money(product["price_cents"] * 4) in body


def test_an_htmx_removal_returns_the_empty_state_in_the_same_region(client, product):
    add(client, product["slug"], 1)
    body = remove(client, product["slug"], htmx=True).text

    assert 'id="cart-contents"' in body
    assert "Your cart is empty" in body
    assert 'id="cart-count" hx-swap-oob="true"' in body


def test_the_htmx_fragment_and_the_page_render_the_same_cart(client, filled):
    """One component behind both, so an edited cart cannot differ from a reloaded one."""
    first, _ = filled
    fragment = update(client, first["slug"], 3, htmx=True).text
    page = client.get("/cart").text

    contents = fragment[fragment.index('<div id="cart-contents">') :]
    assert contents.strip() in page


# --- checkout, which is not here ----------------------------------------------------


def test_checkout_is_present_and_visibly_inert(client, product):
    add(client, product["slug"], 1)
    page = cart_page(client)
    assert "Proceed to Checkout" in page

    start = page.index('<button type="button" disabled')
    button = page[start : page.index("Proceed to Checkout")]
    assert 'aria-disabled="true"' in button
    assert "out of scope" in page


def test_checkout_leads_nowhere(client, product):
    """It is a disabled button, not a link and not a form -- there is nothing behind it."""
    add(client, product["slug"], 1)
    page = cart_page(client)
    assert "/checkout" not in page
    assert client.post("/checkout", follow_redirects=False).status_code == 404
