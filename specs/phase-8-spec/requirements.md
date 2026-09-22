# Phase 8 — Cart: add and view

Roadmap: [Phase 8](../roadmap.md#phase-8--cart-add-and-view). Journey steps 5–6 of
[mission.md](./../mission.md#the-journey-we-own): pick a quantity, add to cart, review
the cart.

## Scope

In:

- `Cart` and `CartItem` models, per the intended data model in
  [tech-stack.md](../tech-stack.md#data-model-intended).
- Anonymous cart identified by a signed `session_token` cookie.
- Quantity picker + Add to Cart on the product detail page.
- `POST /cart/add`, `GET /cart` (read-only line items, per-line totals, subtotal).
- Header cart link becomes live and shows the item count.

Out (named so the boundary is explicit):

- Quantity editing, line removal, empty-cart-with-controls, and the inert
  "Proceed to Checkout" button — **Phase 9**.
- Cookie hardening (Secure flag, lifetime, tamper cases beyond "issue a fresh
  cart"), cross-refresh verification on the deployed URL — **Phase 10**.
- Users and cart merge — Phases 11–12.

## Decisions

| Question | Decision | Why |
| --- | --- | --- |
| Feedback after add | Stay on the detail page. HTMX swaps the header count and renders an inline "Added to cart" confirmation linking to `/cart`. | A silent count change is missable; a redirect breaks browsing. |
| No-JS behaviour | The control is a real `<form method="post" action="/cart/add">` with `hx-post` layered on. Without JS it POSTs and `303`-redirects to `/cart`. | No dead controls ([roadmap](../roadmap.md) rule); write paths degrade instead of dying. |
| Cart page in this phase | Read-only: lines, per-line totals, subtotal, and an empty state. | Matches the roadmap phase boundary; Phase 9 owns mutation. |
| Cookie issuance | Lazy — no cookie and no `Cart` row until the first `POST /cart/add`. | A browsing visitor or crawler should not create rows; keeps the table meaningful. |

## Constraints inherited from the specs

- Money stays in **integer cents** end to end; division happens only at render.
  Line total = `price_cents * quantity`; subtotal = sum of line totals.
- `components/product_card.html` stays the only product tile; the cart line is a
  *different* presentation (row, not tile) and gets its own component rather than
  bending the card.
- Cookie is signed with `SECRET_KEY` and `httpOnly`. The `Secure` flag and lifetime
  policy are Phase 10's; this phase must not make them harder to add.
- Products are addressed by **slug**, not id, in form bodies and URLs.
- Works on SQLite and Postgres; no new dependency.

## Context

- `templates.env.globals["features"]["cart"]` in `app/templating.py` is the single
  switch that turns the inert header cart and the detail-page placeholder into live
  controls. It flips in this phase and nowhere else.
- `base.html` already defines a `{% block cart_link %}` guarded by that flag; the
  placeholder `<span>` next to it is what the live link replaces.
- `product_detail.html` line ~56 holds the "Quantity selection and Add to Cart arrive
  in a later build" placeholder.
- `app/models.py` deliberately ships catalog tables only — adding `Cart`/`CartItem`
  here is the intended point, not a widening.
- Schema comes from models via `create_schema()`; there are no migrations, so the new
  tables appear on the next boot (and the Render start command already re-runs the
  idempotent seed).
