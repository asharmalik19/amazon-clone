"""Helpers shared by the auth and cart-merge test modules.

Phase 11 tests the forms themselves; Phase 12 tests what signing in does to the cart.
Both drive the same three endpoints with the same cookie jar, so the request shapes live
here rather than being copied between the two files.

Passwords are hashed with bcrypt at its default cost, so every signup and every sign-in
attempt costs real time on purpose. That is why the tests share one account where they
can rather than registering a new one per assertion.
"""

import itertools
import re

PASSWORD = "correct-horse-battery"

# Every test writes into the same seeded database, so an address has to be unique per
# account rather than per test file -- one shared counter, so two modules cannot collide.
# A counter rather than a random value: a failure names the account it was looking at, and
# the same run produces the same names.
_addresses = itertools.count(1)


def an_email() -> str:
    return f"shopper{next(_addresses)}@example.com"


def signup(client, *, name="Sam Shopper", email=None, password=PASSWORD, confirm=None):
    """Post the create-account form the way the rendered page does."""
    return client.post(
        "/signup",
        data={
            "name": name,
            "email": email if email is not None else an_email(),
            "password": password,
            "password_confirm": password if confirm is None else confirm,
        },
        # The success path answers with a 303; following it would hide the status under
        # the landing page's 200, and the redirect is part of what is under test.
        follow_redirects=False,
    )


def signin(client, email, password=PASSWORD):
    return client.post(
        "/signin", data={"email": email, "password": password}, follow_redirects=False
    )


def signout(client):
    return client.post("/signout", follow_redirects=False)


def greeting(client) -> str:
    """What the header on the landing page says about who the shopper is."""
    page = client.get("/").text
    match = re.search(r"Hello, (?:sign in|([^<\n]+))", page)
    assert match is not None, "the header said nothing at all about the account"
    return (match.group(1) or "sign in").strip()
