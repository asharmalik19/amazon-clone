"""Who the shopper is: password hashing, the session cookie, and the rules for both.

Everything that decides whether a request belongs to an account lives here, so there is
one answer to "who is this?" rather than one per route. The rules it enforces:

- **A password is never stored.** `hash_password` produces a bcrypt digest -- salt and
  cost included in the string -- and the plaintext exists only for the length of the
  request that typed it. A stolen database yields no passwords.
- **The session cookie is signed, not trusted.** It carries a user id, the moment it was
  issued, and an HMAC of both, keyed by `SECRET_KEY`. A forged, truncated or re-signed
  value is treated as no cookie at all: the visitor is signed out, never signed in as
  somebody else.
- **The lifetime is checked on the server.** `Max-Age` is a request to the browser, and
  a browser is the one party we cannot make keep it. The issue time is inside the signed
  payload, so a cookie replayed after the window has closed is refused here regardless
  of what the client chose to remember.
- **Reads never write.** `read_user` is safe to call while rendering any page; only
  `issue_session` and `clear_session` touch a cookie, and only the auth routes call them.

The signing helpers are the same ones the cart cookie uses -- `app.cart` imports `sign`
and `unsign` from here -- because two HMAC implementations in one app is one more than
can be reviewed. `hmac` and `hashlib` come from the standard library; `bcrypt` is the one
dependency, because writing a password hash is not a thing to do by hand.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time

import bcrypt
from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import User

# --- signing --------------------------------------------------------------------------

# What separates a payload from its signature. `rpartition` splits on the last one, so a
# payload may contain it -- which the session payload below does.
SEPARATOR = "."


def _signature(payload: str) -> str:
    """The HMAC of `payload`, keyed by the application secret, as url-safe base64.

    Padding is stripped so a cookie value stays free of `=`, which would otherwise have
    to be quoted.
    """
    digest = hmac.new(
        get_settings().secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def sign(payload: str) -> str:
    """The cookie value for `payload`: the payload itself, then its signature."""
    return f"{payload}{SEPARATOR}{_signature(payload)}"


def unsign(value: str | None) -> str | None:
    """The payload of `value` if its signature holds, else `None`.

    `None` covers every failure the same way -- absent, malformed, or signed with a
    different key -- because none of them are distinguishable from the visitor's side and
    none of them deserve anything other than being treated as a first visit. In
    particular a rotated `SECRET_KEY` invalidates old cookies rather than crashing on
    them.

    `compare_digest` rather than `==`: the comparison is against attacker-supplied text,
    and a timing difference is the one thing that would make forging a signature easier
    than guessing it.

    The comparison is over **bytes**. `compare_digest` raises `TypeError` on a `str`
    holding anything outside ASCII, and a `Cookie` header is arbitrary bytes that
    Starlette decodes character-for-character -- so one high byte in the signature would
    otherwise be a 500 on a request anyone can send with `curl`. Encoding both sides
    keeps the comparison constant-time and makes the reject path total: there is no
    cookie value that is neither a match nor a mismatch.
    """
    if not value or SEPARATOR not in value:
        return None
    payload, _, signature = value.rpartition(SEPARATOR)
    if not payload:
        return None
    if not hmac.compare_digest(signature.encode("utf-8"), _signature(payload).encode("ascii")):
        return None
    return payload


# --- passwords ------------------------------------------------------------------------

# Amazon asks for at least 6; 8 is the shortest number worth defending, and it is the
# number the form tells the shopper before they type rather than after.
PASSWORD_MIN_LENGTH = 8

# bcrypt hashes at most 72 bytes and **silently ignores** the rest, so a longer password
# would be accepted at signup and then match on its first 72 bytes at sign in -- a
# promise the app cannot keep. It is refused with a visible message instead. Bytes, not
# characters: the limit is on the encoded form, so it depends on the alphabet used.
PASSWORD_MAX_BYTES = 72


def hash_password(password: str) -> str:
    """The bcrypt digest of `password`, ready to store.

    The cost factor is bcrypt's own default (currently 12) rather than a number pinned
    here: it is the value the library maintains as "slow enough today", and it is
    recorded inside the returned string, so raising it later leaves existing hashes
    verifiable without a migration.
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


# What a bcrypt digest looks like: the algorithm tag, the cost, then 53 characters of
# base64 salt and hash. The shape is checked before anything is handed to the library
# because `bcrypt.checkpw` does not merely raise on a malformed hash -- a truncated one
# panics inside its Rust extension, and a `PanicException` is not an `Exception`, so it
# would sail past any ordinary `except` and out of the sign-in route as a 500. A stored
# hash that cannot be read has to mean "you cannot sign in", not a broken form.
_BCRYPT_HASH = re.compile(r"^\$2[abxy]\$\d\d\$[./A-Za-z0-9]{53}$")


def verify_password(password: str, password_hash: str) -> bool:
    """Whether `password` is the one `password_hash` was made from.

    `False` rather than an exception for a hash this app did not write -- a row edited by
    hand, or one left behind by a different algorithm. It fails closed: "you cannot sign
    in" is the safe answer, and a 500 on the sign-in form would be worse for everyone
    but the attacker.
    """
    if not _BCRYPT_HASH.match(password_hash):
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def password_problem(password: str) -> str | None:
    """What is wrong with `password` as a new password, or `None` if nothing is.

    Returned as the sentence the form will show, because there is one place that decides
    what a valid password is and the message a shopper reads should come from it rather
    than being written again next to the field.
    """
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Passwords must be at least {PASSWORD_MIN_LENGTH} characters."
    if len(password.encode("utf-8")) > PASSWORD_MAX_BYTES:
        return f"Passwords must be at most {PASSWORD_MAX_BYTES} characters."
    return None


# --- what an email and a name have to look like ---------------------------------------

# The longest address the standards allow. Also what the column holds.
EMAIL_MAX_LENGTH = 254
NAME_MAX_LENGTH = 120

# Deliberately loose: something, an `@`, then a dotted domain, with no whitespace and no
# second `@`. The only thing that truly validates an address is sending mail to it, which
# this app does not do, so the check is here to catch the typo a shopper can see -- a
# missing `@`, a trailing dot -- and not to adjudicate the grammar of RFC 5322. A stricter
# regex would mostly reject addresses that work.
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


def normalize_email(raw: str) -> str:
    """`raw` in the one form that is ever stored or looked up: trimmed and lowercased.

    Case folding happens here rather than in a query, so "Sam@Example.com" and
    "sam@example.com" cannot become two accounts one person is unable to tell apart. It
    is also why the uniqueness check and the sign-in lookup agree by construction.
    """
    return raw.strip().lower()


def email_problem(email: str) -> str | None:
    """What is wrong with `email`, or `None`. Expects an already-normalized address."""
    if not email:
        return "Enter your email address."
    if len(email) > EMAIL_MAX_LENGTH or not _EMAIL_PATTERN.match(email):
        # The address is not echoed into the message: it is the shopper's own text, and
        # the field above still holds it, so repeating it buys nothing.
        return "Enter a valid email address, like name@example.com."
    return None


def name_problem(name: str) -> str | None:
    """What is wrong with `name`, or `None`. Expects an already-stripped name."""
    if not name:
        return "Enter your name."
    if len(name) > NAME_MAX_LENGTH:
        return f"Names must be at most {NAME_MAX_LENGTH} characters."
    return None


# --- the session cookie ---------------------------------------------------------------

SESSION_COOKIE_NAME = "session"

# How long a signed-in session lasts. The same thirty days the cart cookie gets, for the
# same reason: long enough that coming back next week still finds you signed in, short
# enough that a shared machine does not stay signed in indefinitely. Unlike the cart's,
# this one is not refreshed on every request -- a session has a hard end, and renewing it
# silently would mean it never has one.
SESSION_MAX_AGE_DAYS = 30
SESSION_MAX_AGE = SESSION_MAX_AGE_DAYS * 24 * 60 * 60

# Allowance for a clock that disagrees with itself across a restart or a redeploy. A
# cookie issued "in the future" by less than this is fine; one issued far in the future
# is not a clock problem, it is a forged timestamp, and it is refused.
_CLOCK_SKEW = 60


def issue_session(response: Response, user: User) -> None:
    """Attach a signed session cookie for `user` to `response`.

    `httponly` because no script needs to read it and a stolen session is a stolen
    account. `samesite="lax"` so the cookie still travels when a shopper follows a link
    in from somewhere else, but not on a cross-site POST.

    `secure` comes from the settings rather than from the request, for the reason
    `Settings.cookie_secure` explains -- and it is the same setting the cart cookie
    reads, so the two cannot end up hardened differently.
    """
    payload = f"{user.id}{SEPARATOR}{int(time.time())}"
    response.set_cookie(
        SESSION_COOKIE_NAME,
        sign(payload),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session(response: Response) -> None:
    """Drop the session cookie from the browser.

    The attributes are repeated because a cookie is deleted by being overwritten: a
    browser only replaces a cookie whose name, path and domain match, so "expire it" has
    to be sent with the same `path` it was set with or the old one simply stays.
    """
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        path="/",
    )


def read_session_user_id(request: Request) -> int | None:
    """The user id this request's cookie proves, or `None` if it proves nothing.

    Every failure lands on `None`: no cookie, a forged or truncated one, a payload that
    is not two integers, or a session past `SESSION_MAX_AGE`. From the visitor's side all
    of those are the same situation -- they are not signed in -- and that is a state the
    whole app already renders.
    """
    payload = unsign(request.cookies.get(SESSION_COOKIE_NAME))
    if payload is None:
        return None
    user_id, _, issued_at = payload.partition(SEPARATOR)
    try:
        identifier = int(user_id)
        issued = int(issued_at)
    except ValueError:
        return None
    age = time.time() - issued
    if age > SESSION_MAX_AGE or age < -_CLOCK_SKEW:
        return None
    return identifier


def read_user(db: Session, request: Request) -> User | None:
    """The signed-in shopper, or `None`. Never creates or writes anything.

    This is what every page render calls, so it stays a pure read: a signed-out visitor
    leaves no trace, and a cookie naming an account that no longer exists -- a database
    replaced under a still-valid cookie -- simply looks like a signed-out visitor rather
    than an error page.
    """
    user_id = read_session_user_id(request)
    if user_id is None:
        return None
    return db.scalars(select(User).where(User.id == user_id)).one_or_none()


def find_user_by_email(db: Session, email: str) -> User | None:
    """The account registered to `email`, or `None`. Expects a normalized address.

    One lookup for both write paths -- signup's duplicate check and sign in -- because
    they have to agree about what "this email already has an account" means. Since only
    the normalized form is ever stored, matching it exactly is both correct and index-
    friendly, with no `lower()` around the column to defeat the index.
    """
    return db.scalars(select(User).where(User.email == email)).one_or_none()


# A real bcrypt digest, of a value nobody knows and no account uses. It exists so that a
# sign-in attempt for an address with no account spends the same half-second as one with
# the wrong password: skipping the hash when there is no user would make "no such
# account" measurably faster than "wrong password", which turns the form into a way to
# enumerate who has an account here. It is a committed literal rather than a hash
# computed at import, so no process pays for it at startup.
_ABSENT_USER_HASH = "$2b$12$HkYi3yIngVX1HoJnJjBSfe82HmXes.zb.Bkx.fFnu53ECGPqL8OwG"


def check_credentials(db: Session, email: str, password: str) -> User | None:
    """The account `email` and `password` together prove, or `None`.

    One function for the whole question, so the route never gets to answer "no such
    user" and "wrong password" differently -- by its message or by how long it took.
    Expects an already-normalized address.
    """
    user = find_user_by_email(db, email)
    matches = verify_password(password, user.password_hash if user else _ABSENT_USER_HASH)
    return user if user is not None and matches else None


def create_user(db: Session, *, name: str, email: str, password: str) -> User:
    """Register `email` with `password`. The caller commits.

    Hashing happens here rather than in the route, so there is no path into the table
    that could store a plaintext password by forgetting to call it.
    """
    user = User(name=name, email=email, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    return user
