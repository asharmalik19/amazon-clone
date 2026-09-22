# Phase 10 — Cart persistence hardening

Roadmap: [Phase 10](../roadmap.md#phase-10--cart-persistence-hardening). No new screen
and no new control: this phase makes the cart the previous two phases built actually
survive the way a shopper assumes it does, and makes the one thing standing between a
stranger and that cart — the cookie — hold up when it is attacked rather than used.

Phases 8 and 9 shipped a **session** cookie. It survives navigation and a refresh, which
is what those phases promised, and it is thrown away the moment the browser is closed.
The roadmap's acceptance check for this phase is "close the tab, reopen the site — the
cart is still there", so the cookie needs a lifetime. It also needs `Secure` on a site
served over HTTPS, and it needs to answer a hand-mangled value with an empty cart
instead of a stack trace.

## Scope

In:

- An explicit cookie **lifetime**, so the cart outlives the browser session, and a
  **renewal** on every add so an actively used cart does not expire out from under a
  returning shopper.
- **`Secure` in production**, declared in `render.yaml` rather than inferred, with the
  local HTTP development server still able to hold a cart.
- **Tamper handling that cannot crash.** A cookie whose signature carries bytes outside
  ASCII currently reaches `hmac.compare_digest` as a non-ASCII `str` and raises
  `TypeError` — a 500 on a request a stranger can send with one `curl`. Every malformed
  value has to land on "no cookie", which is already what every other malformed value
  does.
- **A stale but validly signed token** — a cart deleted, or a database replaced under a
  live cookie — issuing a fresh empty cart under a fresh token.
- Tests for cart contents across a sequence of requests, for the cookie's attributes in
  both configurations, and for tampering.
- Verification of all of it **on the live URL**, cookie flags included.

Out (named so the boundary is explicit):

- Users, sign-in, and the anonymous-to-account cart merge — **Phases 11–12**. This phase
  is what makes that merge worth doing: a cart has to be found again before it can be
  claimed.
- Server-side expiry or sweeping of abandoned `Cart` rows. The cookie's lifetime is the
  only expiry in the product; a cart row whose cookie is gone is unreachable and is left
  alone. Deleting rows on a timer is an operational concern with no shopper-visible
  behaviour, and it would need a scheduler the stack deliberately does not have.
- Encrypting the cookie. The token is opaque and random — it carries nothing worth
  hiding, only something worth signing.
- CSRF tokens on the cart forms. `samesite="lax"` already keeps the cookie off a
  cross-site POST, and there is nothing behind the cart to protect.
- Any change to what the cart pages render. If this phase changes a template, it has
  overshot.

## Decisions

| Question | Decision | Why |
| --- | --- | --- |
| Cookie lifetime | 30 days, as `Max-Age` on the cookie. | It has to outlive the browser session or the acceptance check fails, and it has to end sometime or a shared machine hands the next person a basket. 30 days is Amazon's order of magnitude for an anonymous cart and long enough that "I'll come back to it" works. |
| Keeping an active cart alive | Every `POST /cart/add` re-sends the cookie, refreshing the 30 days. | A fixed window from creation would expire a cart a shopper used yesterday because they first filled it a month ago. Renewal on a write is the cheapest correct version: one header on a request that already sets one. |
| Renewal on reads and on the cart edits | No. Only `POST /cart/add` re-sends the cookie. | `read_cart` is called by every page render, and "reads never write" is what keeps browsing traceless — including in the response headers. `POST /cart/update` and `/cart/remove` are forbidden from touching the cookie by [phase 9](../phase-9-spec/validation.md), and an edit is not evidence of a shopper who needs another 30 days; an add is. |
| How `Secure` is decided | `COOKIE_SECURE` in the environment, declared `true` in `render.yaml`; when it is unset, it follows `Settings.is_production`. | `Secure` on a local HTTP server means the browser silently drops the cookie and the cart appears broken with nothing in the logs. Reading the deployed scheme off `X-Forwarded-Proto` would mean trusting a header any client can send. An explicit declaration is right where a reviewer looks for it, and the `is_production` fallback means an unedited deploy is not insecure by omission. |
| Whether to trust proxy headers instead | No. | The only thing the scheme would decide is this one flag, and the cost of getting it from a forwarded header is trusting attacker-supplied text for a security decision across the whole app. A boolean in the blueprint is smaller and cannot be spoofed. |
| Comparing the signature | Compare **bytes**, not `str`. | `hmac.compare_digest` raises `TypeError` on a non-ASCII `str`, and a cookie header arrives as arbitrary bytes decoded one-to-one into a `str`. Encoding both sides first keeps the constant-time comparison and makes the "reject" path total: there is no value a client can send that is not either a valid signature or a mismatch. |
| A tampered cookie on a read | Rendered as an empty cart; the bad cookie is left in place. | It is indistinguishable from a first visit and should look like one. Clearing it would mean a read path setting a header, and the next add overwrites it anyway. |
| A tampered cookie on an add | Treated as absent: a new cart under a new token, which replaces the bad cookie. | Already how `get_or_create_cart` behaves for a stale token. A forged cookie must never resolve to a cart, and it must not lock the shopper out of getting one. |
| A rotated `SECRET_KEY` | Every existing cookie stops verifying, and each shopper's next add issues a new cart. | Stated in `render.yaml` as the intended consequence of rotation. The alternative — a key list with a grace period — is a session-management feature for a product with sessions; this one has an anonymous basket. |
| Cart rows left behind by an expired cookie | Left in the table. | See "out of scope" above: unreachable, harmless, and Phase 12 gives them a second life only when a signed-in shopper still holds the cookie. |

## Constraints inherited from the specs

- The cookie stays `httponly` and `samesite="lax"`, signed with `SECRET_KEY` via stdlib
  `hmac`. No new dependency.
- Reads create nothing: no `Cart` row, no `Set-Cookie`. Only `POST /cart/add` may do
  either.
- No secret in the repo, and no personal or employer-identifying value in the blueprint.
- Works on SQLite and Postgres; `ruff check` and `pytest` clean; live on the deployed
  URL before the phase is done.

## Context

- `app/cart.py` holds the whole cookie story: `sign_token`/`read_token`, `new_token`,
  `set_cart_cookie`, and the `read_cart` vs `get_or_create_cart` split. Its docstring
  already names hardening as this phase's, so the shape it leaves behind is the one to
  fill in.
- `get_or_create_cart` currently returns the new token *only when it made one*, which is
  what makes a second add send no cookie. Renewal changes that contract to "the token
  this cart is found by", and the route sets it after the commit either way.
- `Settings.is_production` is true when `SECRET_KEY` came from the environment — the
  existing, tested signal for "this is the deploy", and the fallback for `COOKIE_SECURE`.
- `tests/test_cart.py` already asserts the phase-8 cookie contract, including
  `test_a_second_add_reuses_the_cookie_it_already_set`, which forbids the renewal this
  phase adds. Its subject — one token, not a new cart per add — survives; its assertion
  that no header is sent does not, and it is rewritten here rather than worked around.
- `tests/cart_helpers.py` drives the cart over HTTP with a browser-like cookie jar, so
  "the cart is still there on the next request" is already expressible.
