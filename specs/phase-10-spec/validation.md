# Phase 10 — Validation

## Gates

- [ ] `ruff check` clean.
- [ ] `pytest` green.
- [ ] Deployed to Render from `main`, health check green, live URL serving the change.

## Automated checks

| Check | Expectation |
| --- | --- |
| Across requests | Add two products, then load `/`, a product page, a search and a category page: `/cart` still has both lines, the same quantities and the same subtotal, under the same token. |
| Re-read | A second `GET /cart` is identical to the first and sets no cookie. |
| Lifetime | `Set-Cookie` carries `Max-Age=2592000` (30 days) -- the attribute browsers use to keep a cookie past the session. |
| Attributes | `HttpOnly`, `Path=/`, `SameSite=lax` on every cart cookie issued. |
| Not secure locally | Under the development settings the cookie has no `Secure` flag, so an HTTP dev server can hold a cart. |
| Secure in production | `COOKIE_SECURE=true` → `Secure` on the header. With `SECRET_KEY` supplied and `COOKIE_SECURE` unset, `Secure` too — a deploy is not insecure by omission. |
| Flag parsing | `true/1/yes/on` → secure; `false/0/no/off` → not; unset or blank → follows `is_production`. |
| Renewal | A second add re-sends the cookie with the same token and a fresh `Max-Age`, and creates no second `Cart` row. |
| Edits never renew | `POST /cart/update` and `POST /cart/remove` send no `Set-Cookie`, with or without a cart. |
| Reads never renew | No `Set-Cookie` on any `GET`, cart or not. |
| Tampered value | `not-a-token`, `token.wrong-signature`, a truncated token, another token's signature, `.`, `` → 200 and the empty state. |
| Tampered bytes | A `Cookie` header sent as raw bytes with a non-ASCII byte in the signature → 200 and the empty state. **This is a 500 before this phase**; it is the regression this check exists for. |
| Rotated key | A cookie signed with a different `SECRET_KEY` is ignored, not fatal. |
| Tampering on a write | An add with a forged cookie succeeds under a new token, and the cart it returns does not contain the real cart's lines. |
| Stale token | A validly signed token naming no row → empty cart; the next add issues a different token and works. |
| Two shoppers | Separate cookie jars stay separate baskets (still true with a lifetime attached). |

## Manual acceptance (local, before the merge)

1. Fill a cart, open DevTools → Application → Cookies: `cart_session` has an expiry
   about 30 days out (the browser turns `Max-Age` into one), `HttpOnly` ✓, `Secure` ✗ (this is HTTP).
2. `document.cookie` in the console does not show `cart_session` — it is httpOnly.
3. Hard-refresh `/cart`: unchanged.

## Manual acceptance (on the live URL, private window)

1. Add two products, one with quantity 2. `/cart` shows both.
2. **Close the tab entirely**, reopen the live URL: the header badge still shows the
   count and `/cart` still lists both lines. This is the roadmap's acceptance check and
   the reason the cookie has a lifetime at all.
3. DevTools on the live cookie: `Secure` ✓, `HttpOnly` ✓, `SameSite=Lax`, expiry ~30
   days out.
4. Edit the cookie's value by one character in DevTools and reload: the empty state, no
   error page. Add something: a new cart, and the edited value is replaced.
5. `curl -i -c jar -b jar` against `/cart/add` and then `/cart` with the same jar: the
   cart comes back for a client that has no browser session at all.
6. A second private window is a second cart.

## Not-done tripwires

The phase is **not** finished if any of these is true:

- The cart is gone after the tab is closed.
- The live `Set-Cookie` has no `Secure`, or the local one has it.
- Any malformed cookie value can produce a 500 — including one that is not valid UTF-8
  or not ASCII.
- A `GET`, a `/cart/update` or a `/cart/remove` sets a cookie.
- An add creates a second cart for a shopper who already has one.
- The cookie has no expiry, or one so long it is effectively permanent.
- A template changed: this phase has no visible surface.
- The live URL and `main` disagree.
