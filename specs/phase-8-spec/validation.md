# Phase 8 — Validation

## Gates

- [ ] `ruff check` clean.
- [ ] `pytest` green (SQLite locally; the suite exercises the same model layer used on
      Postgres).
- [ ] Deployed to Render from `main`, health check green, live URL serving the change.

## Automated checks

| Check | Expectation |
| --- | --- |
| Add once | `POST /cart/add` creates exactly one `CartItem` with the posted quantity. |
| Add again | Same product again sums the quantity; still one line for that product. |
| Subtotal | `GET /cart` shows each line total as `price_cents * quantity` and a subtotal equal to their sum, formatted from integer cents. |
| Empty cart | No cookie → `/cart` returns 200 with the empty state, not a 404 or a crash. |
| Unknown slug | `POST /cart/add` with a slug that does not exist → 404. |
| Bad quantity | `0`, `-1`, `abc`, `9999` → 400; no line created, no cart mutated. |
| Bad cookie | Tampered or unknown `session_token` → 200 with a fresh empty cart. |
| No lazy writes | `GET /`, `/product/{slug}`, `/search`, `/category/{slug}`, `/cart` send no `Set-Cookie` and create no `Cart` row. |
| HTMX vs form | `HX-Request: true` → HTML fragment, 200. Plain POST → `303` with `Location: /cart`. |

## Manual acceptance (on the live URL, private window)

1. Land on `/`. The header cart reads `0` and is a real link — not the greyed-out
   placeholder.
2. Open a product. Pick quantity `2`, click **Add to Cart**. The page stays put, the
   header count becomes `2`, and the inline "Added to cart" confirmation appears with a
   working link to the cart.
3. Click **View cart**. One line, quantity 2, line total = 2 × the unit price, subtotal
   matching, heading reads "Subtotal (2 items)".
4. Go back, add the same product once more → one line, quantity 3. Add a different
   product → two lines, subtotal is the sum.
5. Navigate to `/cart` directly by URL. The cart is still there.
6. Disable JavaScript, add a product from its detail page: it POSTs and lands on
   `/cart` with the item added.
7. Clear cookies, open `/cart`: the empty state renders with a link back to the
   catalog.

## Not-done tripwires

The phase is **not** finished if any of these is true:

- A control on screen does nothing — including any quantity or remove control on the
  cart page, which belongs to Phase 9 and must not be rendered inert here.
- The subtotal is computed in floats anywhere, or a price is reassembled from a
  formatted string.
- A visitor who only browses gets a cookie or a `Cart` row.
- Add-to-cart works only with JavaScript.
- The live URL and `main` disagree.
