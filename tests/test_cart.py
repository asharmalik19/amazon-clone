"""Phase 8: adding a product to the cart, and reading the cart back.

The tests below go through the HTTP surface rather than the model layer, because what
Phase 8 promises is a journey -- pick a quantity on a product page, land on `/cart` with
the right subtotal -- and the cookie is half of how that works. `TestClient` keeps
cookies between requests exactly as a browser does, so "the cart survives navigation" is
something these tests can actually check.

Prices come from the committed catalog, so the arithmetic is asserted against the
numbers a shopper really sees on the live site.
"""

import pytest

from app.cart import COOKIE_NAME, MAX_ADD_QUANTITY, sign_token
from tests.cart_helpers import add, cart_page, line_totals, money, quantity_of


@pytest.fixture
def products(catalog) -> list[dict]:
    """Two different products from the committed catalog."""
    return catalog["products"][:2]


@pytest.fixture
def product(products) -> dict:
    return products[0]


# --- adding ------------------------------------------------------------------------


def test_adding_a_product_creates_one_line_with_that_quantity(client, product):
    assert add(client, product["slug"], 2).status_code == 303
    page = cart_page(client)
    assert product["title"] in page
    assert quantity_of(page, product["slug"]) == 2
    assert page.count("<li ") == 1


def test_adding_the_same_product_again_sums_the_quantity(client, product):
    add(client, product["slug"], 2)
    add(client, product["slug"], 3)
    page = cart_page(client)
    # One line, not two: the unique constraint on (cart, product) is the rule, and
    # summing is how the write path keeps it true.
    assert page.count("<li ") == 1
    assert quantity_of(page, product["slug"]) == 5
    assert money(product["price_cents"] * 5) in page


def test_adding_a_second_product_makes_a_second_line(client, products):
    for entry in products:
        add(client, entry["slug"])
    page = cart_page(client)
    assert page.count("<li ") == 2
    for entry in products:
        assert entry["title"] in page


@pytest.mark.parametrize("body", [{}, {"quantity": ""}])
def test_a_missing_or_blank_quantity_means_one(client, product, body):
    """The form always posts a value, so this is only reachable by hand.

    An absent quantity is not bad input, it is an unstated one, and the smallest thing a
    shopper could have meant is one. FastAPI reads a blank form field as absent too, so
    both spellings land on the same default rather than on an error.
    """
    response = client.post(
        "/cart/add", data={"slug": product["slug"]} | body, follow_redirects=False
    )
    assert response.status_code == 303
    assert quantity_of(cart_page(client), product["slug"]) == 1


def test_an_unknown_slug_is_a_404_and_is_not_echoed_back(client):
    response = add(client, "<script>alert(1)</script>")
    assert response.status_code == 404
    assert "<script>alert" not in response.text
    # Nothing was created on the way to failing.
    assert "Your cart is empty" in cart_page(client)


@pytest.mark.parametrize("bogus", ["0", "-1", "abc", "1.5", "1e1", str(MAX_ADD_QUANTITY + 1)])
def test_a_quantity_the_picker_cannot_produce_is_refused(client, product, bogus):
    """A bad quantity is a hand-built request, so it is refused rather than guessed at."""
    assert add(client, product["slug"], bogus).status_code == 400
    assert "Your cart is empty" in cart_page(client)


def test_the_quantity_picker_offers_exactly_what_the_route_accepts(client, product):
    """One constant behind both, so the control cannot offer a value that would 400."""
    page = client.get(f"/product/{product['slug']}").text
    for value in range(1, MAX_ADD_QUANTITY + 1):
        assert f'<option value="{value}"' in page
    assert f'<option value="{MAX_ADD_QUANTITY + 1}"' not in page


# --- the two ways the add route answers --------------------------------------------


def test_a_plain_form_post_redirects_to_the_cart(client, product):
    """The no-JavaScript path: the browser posts the form and follows a 303 to /cart."""
    response = add(client, product["slug"], 2)
    assert response.status_code == 303
    assert response.headers["location"] == "/cart"


def test_an_htmx_post_gets_a_fragment_and_not_a_page(client, product):
    response = add(client, product["slug"], 2, htmx=True)
    assert response.status_code == 200
    body = response.text
    assert "<!DOCTYPE html>" not in body
    assert "Added to cart" in body
    assert 'href="/cart"' in body
    # The header badge rides along out of band, so one response updates both places.
    assert 'id="cart-count" hx-swap-oob="true"' in body
    assert "View cart (2 items)" in body


def test_the_fragment_reports_the_quantity_now_in_the_cart(client, product):
    """Not the quantity just added: the confirmation must match the cart page."""
    add(client, product["slug"], 2, htmx=True)
    body = add(client, product["slug"], 1, htmx=True).text
    assert "3 in your cart" in body
    assert "View cart (3 items)" in body


# --- the cart page -----------------------------------------------------------------


def test_the_subtotal_is_the_sum_of_the_line_totals(client, products):
    quantities = [3, 2]
    for entry, quantity in zip(products, quantities, strict=True):
        add(client, entry["slug"], quantity)

    page = cart_page(client)
    expected_lines = [e["price_cents"] * q for e, q in zip(products, quantities, strict=True)]
    for total in expected_lines:
        assert money(total) in page
    # The subtotal is stated twice -- beside the list and in the panel -- and both have
    # to be the same number.
    assert line_totals(page).count(money(sum(expected_lines))) == 2
    assert f"Subtotal ({sum(quantities)} items):" in page


def test_the_subtotal_counts_units_rather_than_lines(client, product):
    add(client, product["slug"], 4)
    assert "Subtotal (4 items):" in cart_page(client)


def test_one_item_is_not_called_one_items(client, product):
    add(client, product["slug"], 1)
    assert "Subtotal (1 item):" in cart_page(client)


def test_a_line_links_back_to_the_product(client, product):
    add(client, product["slug"])
    assert f'href="/product/{product["slug"]}"' in cart_page(client)


def test_the_cart_page_offers_no_control_it_cannot_honour(client, product):
    """Every control on the cart page posts somewhere real -- or is visibly disabled.

    Phase 8 asserted the absence of the edit controls; Phase 9 ships them, so what this
    now guards is the rule behind that assertion rather than the phase boundary: nothing
    on the page promises a capability the app does not have. Checkout is the one
    permanent exception (specs/mission.md), and it is rendered `disabled` rather than
    live.
    """
    add(client, product["slug"], 2)
    page = cart_page(client)
    for absent in ("Save for later", "Gift options", "Apply coupon", "/checkout"):
        assert absent not in page


def test_an_empty_cart_is_a_real_screen_with_a_way_out(client):
    page = cart_page(client)
    assert "Your cart is empty" in page
    assert 'href="/"' in page


def test_the_cart_survives_navigation(client, product):
    """The roadmap's acceptance check: add from the detail page, then find it on /cart."""
    add(client, product["slug"], 2)
    client.get("/")
    client.get(f"/product/{product['slug']}")
    assert product["title"] in cart_page(client)


# --- the header badge ---------------------------------------------------------------


def test_the_header_badge_counts_the_units_in_the_cart(client, product):
    assert 'id="cart-count" ' in client.get("/").text
    add(client, product["slug"], 3)
    for path in ("/", f"/product/{product['slug']}", "/cart", "/search?q=a"):
        body = client.get(path).text
        assert "Cart, 3 items" in body, path


def test_the_header_cart_is_live_everywhere_and_the_placeholder_is_gone(client, product):
    for path in ("/", f"/product/{product['slug']}", "/cart"):
        body = client.get(path).text
        assert 'href="/cart"' in body, path
        assert "The cart arrives in a later build" not in body, path


def test_the_404_page_shows_a_cart_link_without_claiming_a_count(client):
    """The one page with no shell context: it must not guess at the cart's contents."""
    body = client.get("/no-such-page").text
    assert body.count('href="/cart"') == 1
    assert "Cart, 0 items" not in body


# --- the cookie ---------------------------------------------------------------------


def test_browsing_sets_no_cookie_and_creates_no_cart(client, product):
    """A visitor who only looks around stays out of the carts table entirely."""
    for path in ("/", f"/product/{product['slug']}", "/cart", "/search?q=a", "/category/books"):
        response = client.get(path)
        assert "set-cookie" not in response.headers, path
    assert not client.cookies


def test_adding_issues_one_signed_httponly_cookie(client, product):
    response = add(client, product["slug"])
    header = response.headers["set-cookie"]
    assert header.startswith(f"{COOKIE_NAME}=")
    assert "HttpOnly" in header
    assert "Path=/" in header
    assert "samesite=lax" in header.lower()
    # Signed: the value is the token and an HMAC of it, not the bare token.
    value = client.cookies[COOKIE_NAME]
    token, _, signature = value.rpartition(".")
    assert token and signature
    assert sign_token(token) == value


def test_a_second_add_reuses_the_token_it_already_issued(client, product):
    """One shopper, one cart: a second add must not mint a second token.

    Phase 8 asserted that the second add sent no cookie at all. Phase 10 re-sends it to
    refresh the expiry (see tests/test_cart_persistence.py), so what is guarded here is
    the part that never changes -- the token, and therefore the cart, is the same one.
    """
    add(client, product["slug"])
    first = client.cookies[COOKIE_NAME]
    second = add(client, product["slug"])
    assert second.headers["set-cookie"].startswith(f"{COOKIE_NAME}={first}")
    assert client.cookies[COOKIE_NAME] == first


@pytest.mark.parametrize(
    "tampered",
    [
        "not-a-token-at-all",
        "token.wrong-signature",
        ".",
        "",
    ],
)
def test_a_tampered_cookie_is_treated_as_no_cookie(client, product, tampered):
    """Never an error, and never someone else's cart: just an empty-handed visitor."""
    add(client, product["slug"], 2)
    client.cookies.set(COOKIE_NAME, tampered)
    page = cart_page(client)
    assert "Your cart is empty" in page
    assert product["title"] not in page


def test_a_signed_token_for_a_cart_that_does_not_exist_gets_a_fresh_one(client, product):
    """A stale-but-validly-signed cookie is a state, not a crash."""
    client.cookies.set(COOKIE_NAME, sign_token("a-token-no-cart-was-ever-saved-under"))
    assert "Your cart is empty" in cart_page(client)

    # ...and adding from that state works, under a new token.
    response = add(client, product["slug"], 2)
    assert response.status_code == 303
    assert "set-cookie" in response.headers
    assert product["title"] in cart_page(client)


def test_two_shoppers_do_not_share_a_cart(client, products):
    """Separate cookie jars, separate baskets -- the whole point of the token."""
    from fastapi.testclient import TestClient

    from app.main import app

    add(client, products[0]["slug"], 2)
    with TestClient(app) as other:
        add(other, products[1]["slug"], 1)
        other_page = cart_page(other)

    assert products[1]["title"] in other_page
    assert products[0]["title"] not in other_page
    assert products[0]["title"] in cart_page(client)


# --- states that are not the happy path --------------------------------------------


def test_the_cart_page_works_against_an_empty_catalog(empty_client):
    """No products to add, but the page still has to answer rather than fail."""
    response = empty_client.get("/cart")
    assert response.status_code == 200
    assert "Your cart is empty" in response.text


def test_adding_from_an_empty_catalog_is_a_404(empty_client, product):
    assert add(empty_client, product["slug"]).status_code == 404
