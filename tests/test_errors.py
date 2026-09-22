"""Phase 13: every failure is a styled page of the storefront, and never a traceback.

Phase 5 gave 404 a page because an unknown slug is a state the detail route has to
handle. These tests cover the rest of the error surface -- the deliberate 400s, the 405
behind a `POST`-only address, and the crash nobody planned for -- plus the promise that
matters most on a public URL: a 500 says one sentence and keeps everything else in the
log.
"""

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cart import MAX_ADD_QUANTITY
from app.db import get_db
from app.main import app

REPO_ROOT = Path(__file__).resolve().parent.parent

# What a leak looks like, whatever leaked it: Starlette's debug page, FastAPI's JSON
# error body, or a Python exception rendered into the template by accident.
LEAKS = ("Traceback", "RuntimeError", '"detail"', "File \"/")


def assert_is_an_error_page(response, *, status: int, heading: str) -> None:
    """The shape every error response has to have: an HTML page at the real status."""
    assert response.status_code == status
    assert "text/html" in response.headers["content-type"]
    assert heading in response.text
    # The point of the page: somewhere to go that is not this page.
    assert "Back to the catalog" in response.text
    assert f"Error {status}" in response.text
    for leak in LEAKS:
        assert leak not in response.text, leak


@pytest.fixture
def product(catalog) -> dict:
    """One product from the committed catalog, for the routes that need a real slug."""
    return catalog["products"][0]


# --- the errors the app raises on purpose -------------------------------------------


def test_an_unrouted_path_is_a_page(client):
    assert_is_an_error_page(
        client.get("/no-such-page"), status=404, heading="We could not find that page."
    )


def test_a_route_that_raised_its_own_sentence_keeps_it(client):
    """`app/errors.py` only supplies copy for an exception that arrived without any."""
    assert_is_an_error_page(
        client.get("/product/no-such-product"),
        status=404,
        heading="We could not find that product.",
    )


def test_the_wrong_method_is_a_page_and_not_a_json_body(client):
    """`GET /signout` was FastAPI's `{"detail": "Method Not Allowed"}` before this."""
    response = client.get("/signout", follow_redirects=False)
    assert_is_an_error_page(
        response, status=405, heading="That address does not answer that kind of request."
    )
    # The header is part of what a 405 means, so the page must not cost the response its
    # correctness to a client that reads it.
    assert response.headers["allow"] == "POST"


def test_a_refused_quantity_is_a_page_that_says_what_is_allowed(client, product):
    """The bare 400 the cart route left behind for this phase to finish."""
    response = client.post("/cart/add", data={"slug": product["slug"], "quantity": "0"})
    assert_is_an_error_page(
        response,
        status=400,
        heading=f"Choose a quantity between 1 and {MAX_ADD_QUANTITY}.",
    )


def test_an_htmx_request_that_fails_gets_the_same_status(client, product):
    """htmx discards the body of a non-2xx response; the status is what it acts on."""
    response = client.post(
        "/cart/add",
        data={"slug": product["slug"], "quantity": "0"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 400
    # Nothing was swapped into the page, so nothing was added to the cart either.
    assert "Your cart is empty" in client.get("/cart").text


# --- the crash nobody planned for ---------------------------------------------------


@pytest.fixture
def crashing_client() -> TestClient:
    """A client whose every request dies inside the database dependency.

    The most realistic 500 this app has: the database goes away mid-request, after
    routing has already picked the page. `raise_server_exceptions=False` makes the test
    client behave like a real server -- returning the 500 response rather than
    re-raising the exception into the test -- which is the only way to assert on what a
    shopper would actually receive.
    """

    def broken_session():
        raise RuntimeError("connection refused: postgres://amazonia:hunter2@db/amazonia")

    app.dependency_overrides[get_db] = broken_session
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        del app.dependency_overrides[get_db]


def test_a_crash_is_a_styled_500_and_not_a_traceback(crashing_client):
    assert_is_an_error_page(
        crashing_client.get("/"), status=500, heading="Something went wrong on our side."
    )


def test_a_crash_tells_the_page_nothing_about_itself(crashing_client):
    """Not the message, not the type. Exception strings are written for developers."""
    body = crashing_client.get("/").text
    assert "connection refused" not in body
    assert "hunter2" not in body
    assert "postgres" not in body


def test_the_crash_reaches_the_log_with_its_traceback(crashing_client, caplog):
    """Hidden from the shopper is not hidden from whoever has to fix it."""
    with caplog.at_level(logging.ERROR, logger="amazonia"):
        crashing_client.get("/")
    record = next(r for r in caplog.records if r.name == "amazonia")
    assert record.exc_info is not None
    assert "connection refused" in caplog.text
    # The request that provoked it, which is the part that makes a traceback actionable.
    assert "GET /" in record.getMessage()


def test_every_page_of_the_site_fails_the_same_way(crashing_client, product):
    """One handler, so no screen has its own idea of what a crash looks like."""
    for path in ("/", "/cart", f"/product/{product['slug']}", "/search?q=fire", "/signin"):
        assert_is_an_error_page(
            crashing_client.get(path), status=500, heading="Something went wrong on our side."
        )


# --- debug output stays off ---------------------------------------------------------


def test_the_app_is_not_in_debug_mode(client):
    """Starlette's debug page would pre-empt the handler above, so this cannot drift.

    It is asserted rather than configured: `debug` is never read from the environment,
    so there is no switch on the deployed app for anyone to flip.
    """
    assert app.debug is False
    assert client.get("/healthz").status_code == 200


def test_the_api_documentation_surface_is_absent(client):
    """A storefront has no API to document, and a schema is a map of it either way."""
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_the_container_does_not_run_the_reloader():
    """`--reload` in production would serve tracebacks from a watching dev server."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    assert "uvicorn app.main:app" in dockerfile
    assert "--reload" not in dockerfile
