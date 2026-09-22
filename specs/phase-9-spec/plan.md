# Phase 9 — Plan

Task groups in order. Each group is committable; the phase is done when
[validation.md](./validation.md) passes end to end on the deployed URL.

## 1. Cart mutation in `app/cart.py`

1. Widen `parse_quantity(raw, *, minimum=1)` so the add route keeps its 1–10 rule and
   the update route can accept `0`. One parser, one ceiling, two floors.
2. `find_item(cart, product)` — the single place that matches a product to a line, used
   by add, update and remove instead of three copies of the same `next(...)`.
3. `set_quantity(db, cart, product, quantity)` → the line, or `None` when the quantity
   was `0` or the line was not there. Removal is `cart.items.remove(item)`, so the
   `delete-orphan` cascade deletes the row and the in-memory cart the response renders
   is already correct.
4. `remove_item(db, cart, product)` → `bool`, idempotent.
5. Neither function commits and neither creates a cart; the route does the first and
   only `POST /cart/add` does the second.

## 2. One cart body, two callers

1. `components/cart_contents.html` — a `cart_contents(cart)` macro wrapping the whole
   thing in `id="cart-contents"`: the filled cart (lines, list subtotal, summary panel)
   or the empty state, chosen inside the macro.
2. `cart.html` becomes the shell plus one call to that macro, so a full page load and a
   mutation response cannot drift apart.
3. `fragments/cart_contents.html` — the mutation response: the re-rendered region plus
   `cart_count_badge(count, oob=true)`.

## 3. The controls on the line

1. Extend `components/qty_picker.html` with `minimum` and keep `selected`: `0` renders
   as `0 (Delete)`, and a `selected` above the ceiling is appended so the picker always
   shows the line's true quantity.
2. `components/cart_line.html` — replace the quantity *text* with a form:
   `action="/cart/update" method="post"`, hidden `slug`, the picker, an **Update**
   button, plus `hx-post` / `hx-target="#cart-contents"` / `hx-swap="outerHTML"`.
3. A second small form beside it posting `/cart/remove` with a **Delete** button, same
   HTMX attributes.
4. Each line gets `id="cart-line-{{ product.slug }}"` for the manual check and for
   tests to count lines by something more specific than `<li`.

## 4. The summary panel

1. Move the subtotal panel into the contents macro and add the inert
   **Proceed to Checkout** button: `disabled`, `aria-disabled="true"`, muted CTA colour,
   with one line of copy naming it as out of scope.
2. Keep both subtotal statements reading `cart.subtotal_cents` — one expression, two
   places, no second computation.

## 5. The routes

1. `POST /cart/update` in `app/routers/cart.py`: resolve the slug (404), parse the
   quantity with `minimum=0` (400), `read_cart` (no creation), apply, commit.
2. `POST /cart/remove`: the same, without a quantity.
3. One `_edited_cart_response(request, cart)` helper shared by both: `HX-Request` → the
   fragment; plain post → `303` to `/cart`.
4. Update the module docstring: the "Phase 9 is deliberately absent" note is no longer
   true.

## 6. Tests

1. `tests/test_cart_edit.py`:
   - update recomputes the line total, both subtotals and the badge;
   - update to `0` removes the line; Delete removes the line;
   - removing the last line renders the empty state;
   - `-1`, `abc`, `11` → 400 and an unchanged cart; unknown slug → 404;
   - updating or removing a product that is not in the cart, or with no cookie at all,
     is a no-op that still answers 200/303 and sets no cookie;
   - HTMX → fragment with the out-of-band badge and no `<!DOCTYPE`; plain post → `303`
     to `/cart`;
   - the picker shows the line's real quantity, including above the ceiling;
   - Checkout is present, `disabled`, and posts nowhere.
2. Replace `test_the_cart_page_offers_no_control_it_cannot_honour` in
   `tests/test_cart.py` — the controls it forbade are this phase's deliverable; what
   survives is that nothing *beyond* this phase (a checkout target, a coupon box) has
   appeared.
3. `ruff check` and `pytest` clean.

## 7. Ship

1. Commit with the `.agent-logs` entries for this phase.
2. Push to `main`, confirm the Render deploy is green, and run the manual acceptance
   check in [validation.md](./validation.md) against the live URL.
