# Phase 8 — Plan

Task groups in order. Each group is committable; the phase is done when
[validation.md](./validation.md) passes end to end on the deployed URL.

## 1. Data model

1. Add `Cart` (id, `user_id` nullable and unused this phase, `session_token` nullable
   + unique index, `created_at`) and `CartItem` (id, `cart_id`, `product_id`,
   `quantity`) to `app/models.py`.
2. `UniqueConstraint(cart_id, product_id)` and `CheckConstraint(quantity >= 1)`.
   Relationships: `Cart.items` (cascade delete-orphan), `CartItem.product`.
3. Keep the module's conventions: docstring explaining why the table exists now,
   integer cents untouched, no float money.

## 2. Cart session and repository

1. `app/cart.py` — the only place that knows about cookies and cart lookup:
   - sign/verify the `session_token` with `SECRET_KEY` (`itsdangerous` if already a
     transitive dep, otherwise `hmac` + `secrets` from the stdlib — no new dependency);
   - `read_cart(db, request)` → existing cart or `None`; never writes;
   - `get_or_create_cart(db, request)` → cart + the token to set, used only by writes;
   - a bad/unknown/tampered token yields a fresh cart rather than an error.
2. `cart_item_count(cart)` and `cart_subtotal_cents(cart)` as pure functions on
   integer cents.

## 3. Header cart count

1. Flip `features["cart"]` to `True` in `app/templating.py`.
2. `components/cart_link.html` — icon, count badge, links to `/cart`, `id="cart-count"`
   as the HTMX swap target.
3. Make the count available to every page render (a small dependency or context helper
   used by the existing routers) so the badge is correct after a full page load, not
   only after an HTMX swap. Reading must not create a cart or set a cookie.

## 4. Quantity picker + Add to Cart on the detail page

1. `components/qty_picker.html` — a labelled `<select name="quantity">` 1–10,
   defaulting to 1.
2. Replace the placeholder block in `product_detail.html` with a real form:
   `method="post" action="/cart/add"`, hidden `slug`, plus
   `hx-post="/cart/add" hx-target="#cart-status" hx-swap="innerHTML"`, Amazon-orange
   CTA. One response has to update two places, so the targeted swap is the
   confirmation region and the header badge rides along out of band.
3. `fragments/cart_added.html` — the inline "✓ Added to cart — View cart (N)"
   confirmation swapped into `#cart-status`, plus the header count re-rendered with
   `hx-swap-oob="true"`. The badge is a macro shared with the header, so the two
   cannot disagree about how a count looks.

## 5. `POST /cart/add`

1. New `app/routers/cart.py`, registered in `app/main.py`.
2. Resolve the slug (404 for unknown), validate quantity (integer, 1–10; reject
   garbage/negative/zero with a 400, not a silent default).
3. Insert the line, or sum quantity onto the existing line for that product.
4. Respond: HTMX request → the fragment from group 4; plain form POST → `303` to
   `/cart`. Set the signed cookie on the response when the cart was just created.

## 6. `GET /cart`

1. `cart.html` — "Shopping Cart" heading, `components/cart_line.html` per line (image,
   title linking to the detail page, unit price, quantity as text, line total), and a
   subtotal panel reading "Subtotal (N items)".
2. Empty state: a clear "Your cart is empty" screen with a link back to the catalog.
   No quantity or remove controls, and no Checkout button, this phase.

## 7. Tests

1. `tests/test_cart.py`: add creates one line; adding the same product again sums the
   quantity rather than duplicating the line; `/cart` shows the correct line totals and
   subtotal; empty state for a visitor with no cookie; 404 for an unknown slug; 400 for
   a bad quantity; no `Set-Cookie` on `GET /`, `/product/{slug}` or `/cart`.
2. HTMX request (`HX-Request: true`) returns a fragment; plain POST returns a `303` to
   `/cart`.
3. `ruff check` and `pytest` clean.

## 8. Ship

1. Commit with the `.agent-logs` entries for this phase.
2. Push to `main`, confirm the Render deploy is green, and run the manual acceptance
   check in [validation.md](./validation.md) against the live URL.
