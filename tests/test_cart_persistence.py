"""Phase 10: the cart is still there later, and the cookie holds up when it is attacked.

Phases 8 and 9 tested what the cart *does*. These tests are about the one thing standing
between a shopper and their basket: the cookie. They come in two halves.

The first half is the promise -- the contents survive a walk around the site, and the
cookie carries the `Max-Age` that makes it survive the browser being closed. A lifetime
is the only part of "close the tab, come back tomorrow" that can be asserted in a test
suite; the rest is in validation.md, done by hand on the live URL.

The second half is the attack. Every malformed cookie has to land on "no cookie" rather
than on an error page or, far worse, on someone else's cart. That includes values httpx
will not even let a normal test send: a `Cookie` header is arbitrary bytes, so one of
these tests hands the app raw bytes outside ASCII, which is the shape that used to be a
500.
"""

from dataclasses import replace

import pytest
from sqlalchemy import func, select

from app.cart import COOKIE_MAX_AGE, COOKIE_NAME, new_token, sign_token
from app.config import DEV_DATABASE_URL, DEV_SECRET_KEY, Settings, get_settings
from app.db import get_sessionmaker
from app.models import Cart
from tests.cart_helpers import add, cart_page, money, quantity_of, remove, update


@pytest.fixture
def products(catalog) -> list[dict]:
    return catalog["products"][:2]


@pytest.fixture
def product(products) -> dict:
    return products[0]


@pytest.fixture(autouse=True)
def settings_are_restored():
    """Settings are cached process-wide, so a test that changes the environment clears it.

    Without this, a test that sets `COOKIE_SECURE` would decide the flag for every test
    that ran after it in the same process.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def cookie_attributes(response) -> dict[str, str]:
    """The attributes of the `Set-Cookie` this response carries, lowercased.

    Flags with no value (`HttpOnly`, `Secure`) land as empty strings, so a test asks
    `"secure" in attrs` for those and compares the value for the rest.
    """
    assert "set-cookie" in response.headers, "this response set no cookie"
    name, _, rest = response.headers["set-cookie"].partition(";")
    assert name.startswith(f"{COOKIE_NAME}=")
    attributes = {}
    for part in rest.split(";"):
        key, _, value = part.strip().partition("=")
        if key:
            attributes[key.lower()] = value
    return attributes


def issued_cookie(response) -> str:
    """The cookie value this response handed out, read off the header.

    Read from the header rather than from the client's jar because these tests put a
    cookie of their own in that jar first: after the server answers, the jar holds two
    entries under one name, and asking it for "the" cart cookie is ambiguous.
    """
    name, _, _ = response.headers["set-cookie"].partition(";")
    key, _, value = name.partition("=")
    assert key == COOKIE_NAME
    return value


def cart_rows() -> int:
    """How many carts exist in the test database, for "this created no second cart"."""
    session = get_sessionmaker()()
    try:
        return session.scalar(select(func.count()).select_from(Cart))
    finally:
        session.close()


# --- the cart is still there ---------------------------------------------------------


def test_the_cart_survives_a_walk_around_the_site(client, products):
    """Every page a shopper might visit between filling the cart and going back to it."""
    quantities = [2, 3]
    for entry, quantity in zip(products, quantities, strict=True):
        add(client, entry["slug"], quantity)
    token = client.cookies[COOKIE_NAME]

    for path in ("/", f"/product/{products[0]['slug']}", "/search?q=a", "/category/books"):
        assert client.get(path).status_code == 200, path

    page = cart_page(client)
    for entry, quantity in zip(products, quantities, strict=True):
        assert quantity_of(page, entry["slug"]) == quantity
    expected = sum(e["price_cents"] * q for e, q in zip(products, quantities, strict=True))
    assert money(expected) in page
    # The same cart, not a new one handed out along the way.
    assert client.cookies[COOKIE_NAME] == token


def test_reloading_the_cart_changes_nothing(client, product):
    """A hard refresh is just another GET, and it must not mutate or re-issue anything."""
    add(client, product["slug"], 2)
    first = cart_page(client)
    response = client.get("/cart")
    assert "set-cookie" not in response.headers
    assert response.text == client.get("/cart").text
    assert first == cart_page(client)


def test_the_cart_is_found_again_by_the_cookie_alone(client, product):
    """What a returning visitor really is: the same token, on a connection with no history.

    A fresh `TestClient` shares nothing with the first one except the cookie value it is
    handed -- which is exactly what a browser has after it is closed and reopened.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    add(client, product["slug"], 2)
    token = client.cookies[COOKIE_NAME]

    with TestClient(app) as returning:
        returning.cookies.set(COOKIE_NAME, token)
        page = cart_page(returning)
    assert product["title"] in page
    assert quantity_of(page, product["slug"]) == 2


# --- the cookie's attributes ---------------------------------------------------------


def test_the_cookie_outlives_the_browser_session(client, product):
    """A cookie with no `Max-Age` dies with the tab, which is the defect this phase fixes."""
    attributes = cookie_attributes(add(client, product["slug"]))
    assert attributes["max-age"] == str(COOKIE_MAX_AGE)
    assert COOKIE_MAX_AGE == 30 * 24 * 60 * 60


def test_the_cookie_is_httponly_site_wide_and_lax(client, product):
    attributes = cookie_attributes(add(client, product["slug"]))
    assert "httponly" in attributes
    assert attributes["path"] == "/"
    assert attributes["samesite"].lower() == "lax"


def test_the_development_cookie_is_not_secure(client, product):
    """A `Secure` cookie on a local HTTP server is dropped, silently, by the browser."""
    assert "secure" not in cookie_attributes(add(client, product["slug"]))
    assert not get_settings().cookie_secure


def test_a_declared_cookie_secure_is_honoured(client, product, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "true")
    get_settings.cache_clear()
    assert "secure" in cookie_attributes(add(client, product["slug"]))


def test_a_deploy_that_declares_nothing_still_gets_a_secure_cookie(client, product, monkeypatch):
    """`render.yaml` says `true`, but omission must not mean "insecure"."""
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    monkeypatch.setenv("SECRET_KEY", "a-real-generated-secret")
    get_settings.cache_clear()
    assert get_settings().is_production
    assert "secure" in cookie_attributes(add(client, product["slug"]))


@pytest.mark.parametrize("declared", ["true", "TRUE", "1", "yes", "on"])
def test_the_spellings_of_yes(declared, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", declared)
    get_settings.cache_clear()
    assert get_settings().cookie_secure


@pytest.mark.parametrize("declared", ["false", "FALSE", "0", "no", "off"])
def test_the_spellings_of_no(declared, monkeypatch):
    """A deploy has to be able to turn it *off* -- behind a plain-HTTP proxy, say."""
    monkeypatch.setenv("COOKIE_SECURE", declared)
    monkeypatch.setenv("SECRET_KEY", "a-real-generated-secret")
    get_settings.cache_clear()
    assert not get_settings().cookie_secure


@pytest.mark.parametrize("unsaid", [None, "", "   "])
def test_saying_nothing_falls_back_to_whether_this_is_a_deploy(unsaid, monkeypatch):
    if unsaid is None:
        monkeypatch.delenv("COOKIE_SECURE", raising=False)
    else:
        monkeypatch.setenv("COOKIE_SECURE", unsaid)
    get_settings.cache_clear()
    assert get_settings().cookie_secure == get_settings().is_production


def test_the_flag_is_a_property_of_the_settings_object():
    """Constructed directly, so the rule is readable without the environment in it."""
    dev = Settings(DEV_DATABASE_URL, DEV_SECRET_KEY, 8000, "amazonia", False)
    deployed = Settings("postgresql+psycopg://u:p@h/db", "a-real-secret", 10000, "amazonia", True)
    assert not dev.cookie_secure
    assert deployed.cookie_secure
    # And the declaration overrides the inference, in both directions.
    assert replace(dev, cookie_secure_override=True).cookie_secure
    assert not replace(deployed, cookie_secure_override=False).cookie_secure


# --- renewal, and who is allowed to renew --------------------------------------------


def test_a_later_add_pushes_the_expiry_out_without_making_a_second_cart(client, product):
    """Thirty days of inactivity, not thirty days of existence."""
    before = cart_rows()
    first = add(client, product["slug"])
    second = add(client, product["slug"])
    # The same cookie, re-sent: same token, same lifetime, counted from now.
    assert first.headers["set-cookie"] == second.headers["set-cookie"]
    assert cookie_attributes(second)["max-age"] == str(COOKIE_MAX_AGE)
    assert cart_rows() == before + 1


def test_editing_the_cart_never_touches_the_cookie(client, product):
    """The phase-9 rule, re-asserted now that an add does re-send it."""
    add(client, product["slug"], 2)
    for response in (update(client, product["slug"], 3), remove(client, product["slug"])):
        assert "set-cookie" not in response.headers


def test_editing_without_a_cart_sets_no_cookie_and_creates_nothing(client, product):
    before = cart_rows()
    for response in (update(client, product["slug"], 3), remove(client, product["slug"])):
        assert response.status_code == 303
        assert "set-cookie" not in response.headers
    assert cart_rows() == before
    assert not client.cookies


def test_no_read_ever_re_issues_the_cookie(client, product):
    """Renewal is a write path's job; a page render stays a pure read."""
    add(client, product["slug"])
    for path in ("/", f"/product/{product['slug']}", "/cart", "/search?q=a", "/category/books"):
        assert "set-cookie" not in client.get(path).headers, path


# --- tampering ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tampered",
    [
        pytest.param("not-a-token-at-all", id="no-separator"),
        pytest.param("token.wrong-signature", id="wrong-signature"),
        pytest.param(".", id="just-the-separator"),
        pytest.param("", id="empty"),
        pytest.param("..", id="empty-token-and-signature"),
        pytest.param(f".{sign_token('x').rpartition('.')[2]}", id="signature-with-no-token"),
    ],
)
def test_a_mangled_cookie_is_an_empty_cart_and_not_an_error(client, product, tampered):
    add(client, product["slug"], 2)
    client.cookies.set(COOKIE_NAME, tampered)
    page = cart_page(client)
    assert "Your cart is empty" in page
    assert product["title"] not in page


def test_a_truncated_token_does_not_resolve(client, product):
    """The near miss: a real cookie with its last character bitten off."""
    add(client, product["slug"], 2)
    client.cookies.set(COOKIE_NAME, client.cookies[COOKIE_NAME][:-1])
    assert "Your cart is empty" in cart_page(client)


def test_another_tokens_signature_does_not_transfer(client, product):
    """A signature is over one token; pairing it with a different one is a forgery."""
    add(client, product["slug"], 2)
    token = sign_token(new_token()).partition(".")[0]
    stolen = client.cookies[COOKIE_NAME].rpartition(".")[2]
    client.cookies.set(COOKIE_NAME, f"{token}.{stolen}")
    assert "Your cart is empty" in cart_page(client)


def test_a_cookie_signed_with_another_key_is_ignored_not_fatal(client, product, monkeypatch):
    """Rotating `SECRET_KEY` invalidates carts, which render.yaml says is the intent."""
    add(client, product["slug"], 2)
    monkeypatch.setenv("SECRET_KEY", "a-different-secret-entirely")
    get_settings.cache_clear()
    assert "Your cart is empty" in cart_page(client)


def test_a_cookie_of_arbitrary_bytes_does_not_crash_the_page(product):
    """The regression this file exists for.

    A `Cookie` header is bytes, decoded character-for-character. A byte above 0x7f in the
    signature therefore reached `hmac.compare_digest` as a non-ASCII `str`, which raises
    `TypeError` -- a 500 anyone could produce with one `curl`. The header is sent as raw
    bytes here because httpx refuses to encode a non-ASCII `str` into one, which is
    precisely why no earlier test caught it.

    A separate client, so the bogus header is the only cookie in play.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as attacker:
        for raw in (
            b"cart_session=abc.\xe9xyz",
            b"cart_session=\xffabc.\xfe",
            b"cart_session=" + bytes(range(0x80, 0x100)),
        ):
            response = attacker.get("/cart", headers={b"Cookie": raw})
            assert response.status_code == 200, raw
            assert "Your cart is empty" in response.text


def test_forging_a_cookie_does_not_reach_anyone_elses_cart(client, products):
    """The failure that would matter: a tampered token resolving to a real basket."""
    from fastapi.testclient import TestClient

    from app.main import app

    add(client, products[0]["slug"], 2)
    real = client.cookies[COOKIE_NAME]

    with TestClient(app) as attacker:
        attacker.cookies.set(COOKIE_NAME, real[:-1] + ("A" if real[-1] != "A" else "B"))
        assert "Your cart is empty" in cart_page(attacker)
        # ...and the add they make next is their own cart, under their own token.
        issued = issued_cookie(add(attacker, products[1]["slug"]))
        assert issued != real
        # Their jar holds the forgery *and* the cookie they were just given; a browser
        # would have replaced one with the other, so the test does too rather than
        # leaving it to chance which one httpx sends.
        attacker.cookies.clear()
        attacker.cookies.set(COOKIE_NAME, issued)
        page = cart_page(attacker)
        assert products[1]["title"] in page
        assert products[0]["title"] not in page

    assert products[0]["title"] in cart_page(client)


def test_a_stale_token_is_replaced_rather_than_trusted(client, product):
    """Signed by us, naming nothing: a cart that was deleted, or a database replaced."""
    stale = sign_token(new_token())
    client.cookies.set(COOKIE_NAME, stale)
    assert "Your cart is empty" in cart_page(client)

    response = add(client, product["slug"], 2)
    assert response.status_code == 303
    fresh = issued_cookie(response)
    assert fresh != stale
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, fresh)
    assert quantity_of(cart_page(client), product["slug"]) == 2
