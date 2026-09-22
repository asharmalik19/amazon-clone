"""Phase 11: signing up, signing in, signing out -- and the ways each of those fails.

Three halves, really.

The first is the journey the roadmap asks for: sign up, sign out, sign back in, with the
header telling the truth about who the shopper is at every step and the account still
there afterwards.

The second is the forms refusing bad input *visibly*. A form that rejects a submission
without saying why is a dead end, so every rejection is asserted to come back as the
form, with the message in it, and with what the shopper typed still in the fields -- and
without the password they typed.

The third is the session cookie, which is the only thing standing between a stranger and
somebody's account. It gets the same treatment Phase 10 gave the cart cookie: forged,
truncated, re-signed, expired, naming a deleted account, or made of bytes no browser
would send -- every one of them has to look exactly like a signed-out visitor rather than
an error page or, far worse, somebody else's session.

Passwords are hashed with bcrypt at its default cost, so each signup and each sign-in
attempt costs real time on purpose. That is why the tests below share one account where
they can rather than registering a new one per assertion.

What signing in does to the *cart* is Phase 12 and lives in test_cart_merge.py. The
helpers the two files share -- posting the three forms, reading the header greeting -- are
in tests/auth_helpers.py.
"""

import time

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import User
from app.security import (
    PASSWORD_MAX_BYTES,
    PASSWORD_MIN_LENGTH,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE,
    hash_password,
    sign,
    verify_password,
)
from tests.auth_helpers import PASSWORD, an_email, greeting, signin, signout, signup


def cookie_attributes(response) -> dict[str, str]:
    """The attributes of the session cookie this response set, lowercased."""
    header = next(
        (value for value in response.headers.get_list("set-cookie") if _is_session(value)),
        None,
    )
    assert header is not None, "this response set no session cookie"
    _, _, rest = header.partition(";")
    attributes = {}
    for part in rest.split(";"):
        key, _, value = part.strip().partition("=")
        if key:
            attributes[key.lower()] = value
    return attributes


def _is_session(header: str) -> bool:
    return header.startswith(f"{SESSION_COOKIE_NAME}=")


def user_count() -> int:
    session = get_sessionmaker()()
    try:
        return len(session.scalars(select(User)).all())
    finally:
        session.close()


def stored_user(email) -> User | None:
    session = get_sessionmaker()()
    try:
        return session.scalars(select(User).where(User.email == email)).one_or_none()
    finally:
        session.close()


@pytest.fixture(autouse=True)
def settings_are_restored():
    """Settings are cached process-wide, so a test that changes the environment clears it."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- the journey ----------------------------------------------------------------------


def test_the_forms_render(client):
    for path, heading in (("/signup", "Create account"), ("/signin", "Sign in")):
        response = client.get(path)
        assert response.status_code == 200, path
        assert heading in response.text
    # And each offers the way across to the other, so neither is a dead end.
    assert "/signin" in client.get("/signup").text
    assert "/signup" in client.get("/signin").text


def test_signup_then_signout_then_signin(client):
    """The roadmap's acceptance check, as one test."""
    email = an_email()

    created = signup(client, name="Ada Lovelace", email=email)
    assert created.status_code == 303
    assert created.headers["location"] == "/"
    # Signed up *is* signed in: a form that made you type your password twice and then
    # asked you to type it a third time would be asking for nothing.
    assert greeting(client) == "Ada Lovelace"

    assert signout(client).status_code == 303
    assert greeting(client) == "sign in"

    assert signin(client, email).status_code == 303
    assert greeting(client) == "Ada Lovelace"


def test_the_account_outlives_the_session(client, account):
    """Signing out ends a session, not an account -- the row is still there afterwards."""
    stored = stored_user(account)
    assert stored is not None
    assert stored.created_at is not None
    # And it is the same account on the way back in, not a second one.
    before = user_count()
    assert signin(client, account).status_code == 303
    assert user_count() == before


def test_the_email_is_stored_and_matched_normalized(client):
    """ "Sam@Example.com" and "  sam@example.com " are one account, not two or none."""
    email = an_email()
    assert signup(client, email=f"  {email.upper()}  ").status_code == 303
    assert stored_user(email) is not None
    signout(client)

    assert signin(client, f" {email.upper()} ").status_code == 303
    assert greeting(client) == "Sam Shopper"


def test_a_password_is_never_stored_in_the_clear(client, account):
    """The whole point of hashing: the database holds no password."""
    stored = stored_user(account)
    assert PASSWORD not in stored.password_hash
    assert stored.password_hash.startswith("$2b$")
    assert verify_password(PASSWORD, stored.password_hash)
    assert not verify_password(PASSWORD + "x", stored.password_hash)


def test_the_header_offers_the_way_in_and_out(client, account):
    """No dead ends: signed out there is a link in, signed in there is a button out."""
    signed_out = client.get("/").text
    assert 'href="/signin"' in signed_out
    assert 'action="/signout"' not in signed_out

    signin(client, account)
    signed_in = client.get("/").text
    assert 'action="/signout"' in signed_in
    assert 'href="/signin"' not in signed_in


def test_sign_out_is_not_a_link(client, account):
    """A `GET /signout` would let any other site sign a shopper out with an `<img>`."""
    signin(client, account)
    assert client.get("/signout", follow_redirects=False).status_code == 405
    assert greeting(client) != "sign in"


def test_signing_out_when_nobody_is_signed_in(client):
    """A double-submitted button, or a stale second tab. The asked-for state either way."""
    response = signout(client)
    assert response.status_code == 303
    assert greeting(client) == "sign in"


# --- the signup form's refusals -------------------------------------------------------


def test_a_duplicate_email_is_refused_visibly(client, account):
    before = user_count()
    response = signup(client, email=account)
    assert response.status_code == 400
    assert "already has an account" in response.text
    assert user_count() == before


def test_a_duplicate_in_another_case_is_still_a_duplicate(client, account):
    response = signup(client, email=account.upper())
    assert response.status_code == 400
    assert "already has an account" in response.text


@pytest.mark.parametrize(
    "email",
    [
        pytest.param("", id="blank"),
        pytest.param("   ", id="spaces"),
        pytest.param("sam", id="no-at"),
        pytest.param("sam@example", id="no-dot"),
        pytest.param("sam@@example.com", id="two-ats"),
        pytest.param("sam@example.", id="trailing-dot"),
        pytest.param("@example.com", id="no-local-part"),
        pytest.param("s am@example.com", id="inner-space"),
    ],
)
def test_an_unusable_email_is_refused_visibly(client, email):
    before = user_count()
    response = signup(client, email=email)
    assert response.status_code == 400
    assert ("valid email address" in response.text) or ("Enter your email" in response.text)
    assert user_count() == before


def test_a_short_password_is_refused_with_the_rule(client):
    response = signup(client, password="short")
    assert response.status_code == 400
    assert f"at least {PASSWORD_MIN_LENGTH} characters" in response.text


def test_a_password_bcrypt_would_silently_truncate_is_refused(client):
    """bcrypt ignores everything past 72 bytes, so accepting more would be a promise
    the app cannot keep at sign-in time."""
    response = signup(client, password="p" * (PASSWORD_MAX_BYTES + 1))
    assert response.status_code == 400
    assert f"at most {PASSWORD_MAX_BYTES} characters" in response.text


def test_the_limit_is_on_bytes_not_characters(client):
    """A 30-character password of 3-byte characters is over bcrypt's limit."""
    response = signup(client, password="±" * 40)
    assert response.status_code == 400
    assert f"at most {PASSWORD_MAX_BYTES} characters" in response.text


def test_mistyping_the_password_twice_is_caught_before_the_account_exists(client):
    before = user_count()
    response = signup(client, password=PASSWORD, confirm=PASSWORD + "x")
    assert response.status_code == 400
    assert "do not match" in response.text
    assert user_count() == before


def test_a_missing_name_is_refused(client):
    response = signup(client, name="   ")
    assert response.status_code == 400
    assert "Enter your name" in response.text


def test_every_problem_is_reported_at_once(client):
    """One trip through the form, not one problem per submission."""
    response = signup(client, name="", email="nope", password="x", confirm="y")
    assert response.status_code == 400
    assert "Enter your name" in response.text
    assert "valid email address" in response.text
    assert f"at least {PASSWORD_MIN_LENGTH} characters" in response.text


def test_a_rejected_signup_keeps_what_was_typed_but_not_the_password(client):
    secret = "a-very-memorable-password"
    response = signup(client, name="Grace Hopper", email="nope", password=secret)
    assert response.status_code == 400
    # The name and email come back, so the shopper fixes the form instead of refilling it.
    assert 'value="Grace Hopper"' in response.text
    assert 'value="nope"' in response.text
    # The password does not: a rejected form must not leave a plaintext password in the
    # page source, a proxy log, or the browser's back-button cache.
    assert secret not in response.text


def test_a_rejected_signup_signs_nobody_in(client):
    response = signup(client, email="nope")
    assert not any(_is_session(header) for header in response.headers.get_list("set-cookie"))
    assert greeting(client) == "sign in"


# --- the signin form's refusals -------------------------------------------------------


def test_a_wrong_password_is_refused_without_saying_which_half_was_wrong(client, account):
    response = signin(client, account, "not-the-password")
    assert response.status_code == 400
    assert "That email or password is not right." in response.text
    assert greeting(client) == "sign in"


def test_an_unknown_email_gets_the_same_answer_as_a_wrong_password(client, account):
    """Otherwise the form is a way to find out who has an account here."""
    wrong_password = signin(client, account, "not-the-password")
    unknown = signin(client, "nobody-here@example.com")
    assert unknown.status_code == wrong_password.status_code == 400
    assert "That email or password is not right." in unknown.text
    # The email is echoed back so it can be corrected; the account's existence is not
    # disclosed by a different message.
    assert "already has an account" not in unknown.text


def test_a_refused_signin_keeps_the_email_and_drops_the_password(client, account):
    response = signin(client, account, "not-the-password")
    assert f'value="{account}"' in response.text
    assert "not-the-password" not in response.text


def test_an_empty_signin_is_a_form_not_a_crash(client):
    response = client.post("/signin", data={}, follow_redirects=False)
    assert response.status_code == 400
    assert "That email or password is not right." in response.text


def test_an_account_cannot_be_signed_into_with_a_leading_space_password(client, account):
    """Whitespace is part of a password, unlike an email address."""
    assert signin(client, account, f" {PASSWORD}").status_code == 400


# --- the session cookie ---------------------------------------------------------------


def test_the_cookie_outlives_the_browser_session(client, account):
    attributes = cookie_attributes(signin(client, account))
    assert attributes["max-age"] == str(SESSION_MAX_AGE)
    assert SESSION_MAX_AGE == 30 * 24 * 60 * 60


def test_the_cookie_is_httponly_site_wide_and_lax(client, account):
    attributes = cookie_attributes(signin(client, account))
    assert "httponly" in attributes
    assert attributes["path"] == "/"
    assert attributes["samesite"].lower() == "lax"


def test_the_development_cookie_is_not_secure(client, account):
    """A `Secure` cookie on a local HTTP server is dropped, silently, by the browser."""
    assert "secure" not in cookie_attributes(signin(client, account))


def test_a_deployed_cookie_is_secure(client, account, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "true")
    get_settings.cache_clear()
    assert "secure" in cookie_attributes(signin(client, account))


def test_signing_out_clears_the_cookie_with_the_same_attributes(client, account):
    """A cookie is deleted by being overwritten, and only a matching path overwrites it."""
    signin(client, account)
    attributes = cookie_attributes(signout(client))
    assert attributes["max-age"] == "0"
    assert attributes["path"] == "/"
    assert "httponly" in attributes
    assert SESSION_COOKIE_NAME not in client.cookies


def test_no_read_ever_issues_a_session_cookie(client, account, catalog):
    """Rendering a page cannot sign anyone in or out."""
    signin(client, account)
    paths = ("/", f"/product/{catalog['products'][0]['slug']}", "/cart", "/signin", "/signup")
    for path in paths:
        headers = client.get(path).headers.get_list("set-cookie")
        assert not any(_is_session(header) for header in headers), path


@pytest.mark.parametrize(
    "tampered",
    [
        pytest.param("not-a-cookie-at-all", id="no-separator"),
        pytest.param("1.999999999.wrong-signature", id="wrong-signature"),
        pytest.param("", id="empty"),
        pytest.param(".", id="just-the-separator"),
        pytest.param(sign("not-a-number"), id="payload-is-not-an-id"),
        pytest.param(sign("1"), id="no-issue-time"),
        pytest.param(sign("1.not-a-time"), id="issue-time-is-not-a-number"),
        pytest.param(sign("1.99999999999"), id="issued-in-the-future"),
    ],
)
def test_a_mangled_session_cookie_is_a_signed_out_visitor(client, tampered):
    client.cookies.set(SESSION_COOKIE_NAME, tampered)
    assert greeting(client) == "sign in"


def test_a_truncated_cookie_does_not_resolve(client, account):
    """The near miss: a real cookie with its last character bitten off."""
    signin(client, account)
    client.cookies.set(SESSION_COOKIE_NAME, client.cookies[SESSION_COOKIE_NAME][:-1])
    assert greeting(client) == "sign in"


def test_an_expired_session_is_refused_by_the_server(client, account):
    """`Max-Age` is a request to the browser; the window is enforced here regardless."""
    user = stored_user(account)
    issued = int(time.time()) - SESSION_MAX_AGE - 1
    client.cookies.set(SESSION_COOKIE_NAME, sign(f"{user.id}.{issued}"))
    assert greeting(client) == "sign in"
    # One second inside the window still works, so it is the age being checked and not
    # the shape of the cookie.
    client.cookies.set(SESSION_COOKIE_NAME, sign(f"{user.id}.{int(time.time()) - 60}"))
    assert greeting(client) == "Sam Shopper"


def test_a_cookie_signed_with_another_key_is_ignored_not_fatal(client, account, monkeypatch):
    """Rotating `SECRET_KEY` signs everybody out, which render.yaml says is the intent."""
    signin(client, account)
    monkeypatch.setenv("SECRET_KEY", "a-different-secret-entirely")
    get_settings.cache_clear()
    assert greeting(client) == "sign in"


def test_a_cookie_naming_an_account_that_does_not_exist(client):
    """Signed by us, naming nobody: a deleted account, or a database replaced under it."""
    client.cookies.set(SESSION_COOKIE_NAME, sign(f"{10**9}.{int(time.time())}"))
    assert greeting(client) == "sign in"


def test_a_cookie_of_arbitrary_bytes_does_not_crash_the_page():
    """A `Cookie` header is bytes, and `compare_digest` raises on a non-ASCII `str`.

    The same regression Phase 10 fixed for the cart cookie, asserted for the session
    cookie -- the two now share one verifier, and this is what proves the shared path is
    the hardened one. A separate client, so the bogus header is the only cookie in play.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as attacker:
        for raw in (
            b"session=1.\xe9xyz",
            b"session=\xffabc.\xfe",
            b"session=" + bytes(range(0x80, 0x100)),
        ):
            response = attacker.get("/", headers={b"Cookie": raw})
            assert response.status_code == 200, raw
            assert "Hello, sign in" in response.text


def test_one_shoppers_cookie_is_not_anothers(client, account):
    """The failure that would matter: a forged cookie landing inside a real account."""
    from fastapi.testclient import TestClient

    from app.main import app

    signin(client, account)
    real = client.cookies[SESSION_COOKIE_NAME]

    with TestClient(app) as attacker:
        attacker.cookies.set(SESSION_COOKIE_NAME, real[:-1] + ("A" if real[-1] != "A" else "B"))
        assert greeting(attacker) == "sign in"
    # ...and the real session is untouched by the attempt.
    assert greeting(client) == "Sam Shopper"


# --- the hashing itself ---------------------------------------------------------------


def test_hashing_is_salted_and_verifiable():
    """Two hashes of one password differ, and both verify. No salt column needed."""
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)
    assert first != second
    assert verify_password(PASSWORD, first)
    assert verify_password(PASSWORD, second)


@pytest.mark.parametrize("stored", ["", "not-a-hash", "$2b$12$too-short", "plaintext-password"])
def test_an_unreadable_hash_fails_closed(stored):
    """A row written by hand must mean "you cannot sign in", not a 500 on the form."""
    assert not verify_password(PASSWORD, stored)
