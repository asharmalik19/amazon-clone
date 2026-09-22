# Phase 10 — Plan

Task groups in order. Each group is committable; the phase is done when
[validation.md](./validation.md) passes end to end on the deployed URL.

## 1. The `Secure` decision, in `app/config.py`

1. `env_flag(name)` → `bool | None`: `1/true/yes/on` and `0/false/no/off`,
   case-insensitively, `None` when unset or blank. One parser, because Phase 13 will
   want a second flag.
2. `Settings.cookie_secure_override: bool | None = None`, read from `COOKIE_SECURE` in
   `get_settings`. Appended with a default so nothing that constructs `Settings`
   positionally has to change.
3. `Settings.cookie_secure` property: the override when it is set, otherwise
   `is_production`. That is the whole rule, and it reads as one line.

## 2. The cookie, in `app/cart.py`

1. `COOKIE_MAX_AGE_DAYS = 30` and `COOKIE_MAX_AGE = COOKIE_MAX_AGE_DAYS * 24 * 60 * 60`
   — the number a person reasons about, and the number the header wants.
2. `set_cart_cookie` gains `max_age=COOKIE_MAX_AGE` and
   `secure=get_settings().cookie_secure`. Its docstring stops calling the flag "Phase
   10's".
3. `read_token`: compare `signature.encode("utf-8")` against
   `_signature(token).encode("ascii")`. Constant-time still, total now — a non-ASCII
   signature is a mismatch rather than a `TypeError`.
4. `get_or_create_cart` returns `tuple[Cart, str]` — the token the cart is found by,
   whether or not it was just created — so the caller can refresh the cookie. Update the
   docstring: the caller always sets the cookie, still only after the commit.

## 3. The add route, in `app/routers/cart.py`

1. Take the token unconditionally and `set_cart_cookie(response, token)` after
   `db.commit()`, replacing the `if new_token is not None` branch. One line shorter, and
   the comment now says why every add renews rather than why some adds set.
2. Nothing in `POST /cart/update` or `/cart/remove` changes. They still never set a
   cookie; the phase-9 tripwire stays armed.

## 4. `render.yaml`

1. `COOKIE_SECURE: "true"` alongside `SECRET_KEY`, with a comment saying the app falls
   back to inferring it and that this is the declaration a reviewer should be able to
   find.

## 5. Tests

1. `tests/test_cart_persistence.py`:
   - the cart survives a sequence of page loads and a re-read of `/cart`, with the same
     token throughout;
   - the cookie's attributes: `HttpOnly`, `Path=/`, `SameSite=lax` and `Max-Age` equal
     to the constant — this is the "close the tab" promise in header form, since a
     cookie carrying a `Max-Age` is the only kind that survives it;
   - no `Secure` under the development settings; `Secure` when `COOKIE_SECURE=true`, and
     when `SECRET_KEY` is supplied and `COOKIE_SECURE` is not;
   - a second add renews the lifetime under the same token and creates no second cart;
   - tampering, including a cookie header sent as raw non-ASCII **bytes** — the value
     that is a 500 before this phase — plus a truncated token, another token's signature,
     and a signature made with a different key: every one is 200 and an empty cart;
   - a tampered cookie on a *write*: the add succeeds under a new token and the old
     cart's contents do not reappear;
   - a stale but validly signed token: empty cart, then an add under a new token;
   - `COOKIE_SECURE` parsing, on the settings object, for the spellings a platform
     actually produces.
2. `tests/test_cart.py::test_a_second_add_reuses_the_cookie_it_already_set` becomes
   `..._reuses_the_token_it_already_issued`: same token, no new cart, and now a refreshed
   cookie rather than no cookie.
3. `tests/test_deploy.py`: the blueprint declares `COOKIE_SECURE`.
4. `ruff check` and `pytest` clean.

## 6. Verify, then ship

1. Run the app locally against a scratch database, fill a cart in the browser, and check
   the cookie in DevTools: `Max-Age` present, `HttpOnly` set, `Secure` absent over HTTP.
   Leave it running for review.
2. Commit with the `.agent-logs` entries for this phase.
3. After the merge to `main`, confirm the Render deploy is green and run the live checks
   in [validation.md](./validation.md) — including `Secure` on the real `Set-Cookie` and
   a cart found again by a cookie jar that was never in a browser session.
