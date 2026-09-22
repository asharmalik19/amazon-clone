# Phase 9 — Cart: change quantity, remove, subtotal

Roadmap: [Phase 9](../roadmap.md#phase-9--cart-change-quantity-remove-subtotal). The
back half of journey step 6 of [mission.md](../mission.md#the-journey-we-own): review the
cart — and change your mind about it.

Phase 8 left the cart page deliberately read-only. This phase makes it editable, which
is also the phase that finally lets the shopper *empty* their cart, so the empty state
stops being a screen only a first-time visitor sees.

## Scope

In:

- `POST /cart/update` — set a line's quantity; `0` removes the line.
- `POST /cart/remove` — drop a line outright.
- Per-line quantity picker and Delete control on `/cart`, both real forms with HTMX
  layered on, both re-rendering the line, the subtotal and the header badge.
- The empty-cart state reached by removing the last line, not only by arriving without
  a cookie.
- **Proceed to Checkout**, present and visibly inert, per
  [mission.md](../mission.md#explicitly-out-of-scope).
- Money maths asserted in integer cents.

Out (named so the boundary is explicit):

- Cookie hardening — `Secure`, lifetime, deployed cross-refresh proof — **Phase 10**.
- Users, sign-in and cart merge — **Phases 11–12**.
- "Save for later", quantity typed into a free-text box, line-level price history —
  not on the roadmap at all.
- Any step past the cart. Checkout stays out of scope permanently; this phase renders
  the button and nothing behind it.

## Decisions

| Question | Decision | Why |
| --- | --- | --- |
| What a mutation answers with | The whole cart contents region, re-rendered, plus the header badge out of band. | One update changes the line, both subtotals and the badge. A region swap keeps them consistent by construction; four targeted swaps would be four chances to disagree. |
| How a quantity change is submitted | `<select>` 0–10 plus a visible **Update** button, in a real form. HTMX posts it on submit. | Auto-submitting on `change` would leave the no-JS path with a select that does nothing until a button it cannot see is pressed. One control, one visible way to commit it, with or without script. |
| `0` in the picker | Offered, labelled `0 (Delete)`, and removes the line — the same outcome as the Delete button. | The roadmap asks for it, Amazon offers it, and a shopper who picks 0 has said what they mean. |
| A line whose quantity already exceeds 10 | The picker still shows the true quantity as a selected option; the ceiling only bounds what can be *chosen*. | Repeated adds can legitimately reach 20 (see `MAX_ADD_QUANTITY` in `app/cart.py`). A picker that silently displayed "10" would misreport the cart. |
| Mutating with no cart, or a product that is not in the cart | No-op, then render the cart as it is — not a 404. | A double-submitted Delete, a stale tab, or a cleared cookie are all "that line is already gone". The shopper's intent is satisfied; an error page would be a lie. |
| Unknown slug / unparseable quantity | 404 / 400, exactly as `POST /cart/add` answers them. | Those are hand-built requests, not shopper mistakes, and the cart routes should not disagree about what a valid request looks like. |
| Mutations and cart creation | The mutation routes read the cart; they never create one and never set a cookie. | Only `POST /cart/add` may bring a cart into existence. An "update" that created an empty cart would put rows in `carts` for requests that changed nothing. |
| Checkout button | Rendered `disabled` with `aria-disabled`, plus one line of copy saying why. | The roadmap forbids controls that do nothing *and* silently pretend otherwise; inert-and-labelled is the allowed third state. |

## Constraints inherited from the specs

- Money stays in **integer cents** end to end. Line total = `price_cents * quantity`,
  subtotal = sum of line totals, division only in `components/price.html`.
- Read paths work without JavaScript, and per
  [tech-stack.md](../tech-stack.md) the write paths degrade to a page navigation rather
  than to a dead button: every control is a real form posting to a real URL.
- `components/product_card.html` stays the browse-only tile; the cart line stays its own
  component.
- Products are addressed by **slug** in form bodies.
- No new dependency. Works on SQLite and Postgres.

## Context

- `app/cart.py` owns cookie identity and cart lookup; `parse_quantity` is the one place
  that decides what a quantity is, and `MAX_ADD_QUANTITY` the one place that bounds it.
- `app/models.py` already provides `CartItem.line_total_cents`, `Cart.subtotal_cents`
  and `Cart.item_count`; the cascade on `Cart.items` is `delete-orphan`, so removing a
  line from the collection deletes the row.
- `components/cart_link.html` exposes `cart_count_badge(count, oob=false)` — the shared
  badge the fragment re-renders out of band.
- `cart.html` currently inlines both the filled and the empty cart. This phase lifts
  that body into a component so a mutation response and a full page load render the same
  markup.
- `tests/test_cart.py::test_the_cart_page_offers_no_control_it_cannot_honour` asserts the
  absence of exactly what this phase adds. It is the phase-8 boundary marker and is
  replaced here, not worked around.
