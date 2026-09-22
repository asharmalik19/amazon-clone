# Phase 9 — Validation

## Gates

- [ ] `ruff check` clean.
- [ ] `pytest` green.
- [ ] Deployed to Render from `main`, health check green, live URL serving the change.

## Automated checks

| Check | Expectation |
| --- | --- |
| Update | `POST /cart/update` with `quantity=5` sets the line to 5; line total = `5 * price_cents`; both subtotals and the header badge follow. |
| Update to 0 | The line is gone, the cart row is not. |
| Remove | `POST /cart/remove` drops that line and leaves the others alone. |
| Last line removed | The response and a subsequent `GET /cart` both render the empty state. |
| Bad quantity | `-1`, `abc`, `1.5`, `11` → 400, cart unchanged. |
| Unknown slug | → 404, cart unchanged. |
| Not in the cart | Updating or removing a product that is not in the cart → no error, cart unchanged. |
| No cart at all | Mutating with no cookie → no crash, no `Set-Cookie`, no `Cart` row, empty state rendered. |
| HTMX vs form | `HX-Request: true` → fragment containing `#cart-contents` and the out-of-band `#cart-count`, no `<!DOCTYPE`. Plain post → `303` with `Location: /cart`. |
| Picker fidelity | The line's select has the line's current quantity selected, even when it exceeds `MAX_ADD_QUANTITY`, and offers `0`. |
| Checkout | The button is rendered, `disabled`, `aria-disabled="true"`, and belongs to no form and no link. |
| Integer cents | Every asserted total is computed as `price_cents * quantity` in Python ints and compared against the rendered string. |

## Manual acceptance (on the live URL, private window)

1. Add two different products, one of them with quantity 2. Open `/cart`.
2. Change the first line's quantity to 4 and press **Update**: the page does not
   navigate, the line total becomes 4 × unit price, both subtotals and the header badge
   update, and the picker shows 4.
3. Press **Delete** on the second line: the line disappears, the subtotal drops by
   exactly that line's total.
4. Set the remaining line's quantity to **0 (Delete)**: the empty state appears, with a
   link back to the catalog, and the header badge goes back to `0`.
5. Reload `/cart`: still empty. Add something again — it comes back with the right count.
6. **Proceed to Checkout** is visible, greyed out, cannot be clicked or focused into a
   submit, and says it is out of scope.
7. Disable JavaScript and repeat steps 2–4: each control posts and lands back on `/cart`
   with the change applied.
8. Clear cookies and post an update by hand (or just reload `/cart`): the empty state,
   no error.

## Not-done tripwires

The phase is **not** finished if any of these is true:

- A cart control works only with JavaScript.
- The subtotal beside the list and the one in the panel can show different numbers.
- Removing the last line leaves a bare "Shopping Cart" heading over nothing.
- A mutation creates a cart row or sets a cookie.
- The Checkout button looks live, or leads anywhere.
- A float or a formatted string is involved in any money arithmetic.
- The live URL and `main` disagree.
