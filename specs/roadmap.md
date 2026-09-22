# Roadmap

The fastest way to a real product is to build **few things, finished**. So: small
**vertical slices**, where data, server, and UI move together and every phase
ends with a capability a shopper can actually use — not a layer that only makes
sense once some later phase lands.

Rules for every phase:

- It is not done until `ruff check` and `pytest` pass.
- It is not done until the acceptance check can be performed by hand in a browser.
- It is not done until its **failure and empty states** work too — bad input,
  no results, missing record. A feature that only works when used correctly is
  not finished.
- **From Phase 2 onward, it is not done until it is live on the deployed URL.**
- No phase leaves behind a control that does nothing. If it is on screen, it
  works, or it is visibly and deliberately inert.
- If a phase turns out to need something from a later phase, stop and re-order
  the roadmap rather than quietly widening the phase.

Deployment is Phase 2, not the last phase. A publicly reachable app is part of
the product, so it gets built while the app is still a header and a placeholder
— when breaking it costs nothing. Every later phase then reaches production as a
side effect of being committed, and there is never an un-deployed backlog.

---

## Phase 1 — Walking skeleton

Runnable FastAPI app with one page.

- `pyproject.toml`, venv, dependencies pinned.
- `app/main.py`, `app/config.py` (settings from env, local defaults), static and
  Jinja2 wiring.
- `base.html` with the Amazon-inspired dark header shell (logo, search input,
  cart link) and footer. Tailwind + HTMX via CDN.
- Home route renders `base.html` with a placeholder body.
- `GET /healthz` → 200.
- `ruff` config, `pytest` with a smoke test asserting `GET /` and `/healthz`
  are 200.

**Accept:** `uvicorn app.main:app --reload` serves a page with a recognisable
Amazon-style header at `/`.

---

## Phase 2 — Deploy the skeleton

The live link exists today, with nothing on it worth breaking.

- `Dockerfile` + `.dockerignore`; the app runs in the container locally on
  `$PORT`.
- `render.yaml` declaring the web service and a Postgres instance.
- `DATABASE_URL` and `SECRET_KEY` set in Render; `psycopg` added; the app boots
  against Postgres as well as SQLite.
- Auto-deploy from `main` enabled; health check pointed at `/healthz`.
- Public URL recorded in the README.

**Accept:** the `*.onrender.com` URL opens the header page for a signed-out
stranger in a private window, and a push to `main` redeploys it automatically.

---

## Phase 3 — Data model and seed

The catalog exists in the database — both databases.

- `app/db.py`, `app/models.py` for `Category`, `Product`, `ProductImage`.
- `seed/products.json` transcribed from `amazon_screenshots/`: ~6 categories,
  ~40–60 products with title, price (integer cents), rating, rating_count,
  description, key-info bullets, image paths.
- Placeholder image files in `app/static/products/`.
- `seed/seed.py` — idempotent and re-runnable, creates schema if absent, works
  on SQLite and Postgres.
- Seed wired into the Render start command.
- Test: seed into a temp DB, assert counts and that every product has a category
  and ≥1 image; assert re-running the seed changes nothing.

**Accept:** `python -m seed.seed` populates the local DB, and the deployed
Postgres is seeded on release.

---

## Phase 4 — Landing page catalog grid

The first real screen.

- `components/product_card.html` — image, title, price, rating. This component
  is the *only* way products are ever rendered; every later screen reuses it.
- `components/stars.html`, `components/price.html` (large whole part, small
  superscript cents).
- `GET /` lists products in a responsive dense grid.
- Test: `GET /` contains the seeded product titles.

**Accept:** the live URL shows the catalog; each tile shows image, title, price,
rating.

---

## Phase 5 — Product detail page

- `GET /product/{slug}` → title, image gallery, price, rating + count,
  description, key-info bullets.
- Product cards link to it. 404 for an unknown slug.
- Test: 200 and expected content for a known slug; 404 for a bad one.

**Accept:** clicking any tile on the home page opens a complete detail page.

---

## Phase 6 — Search

- `GET /search?q=` — case-insensitive match over title, description, key info,
  and category name.
- The header search form posts here; results reuse `product_card.html`.
- Empty query → the full catalog. No matches → a clear empty state echoing the
  query.
- Tests: exact-word hit, partial hit, no-match empty state, blank query.

**Accept:** typing a product name in the header search returns that product.

---

## Phase 7 — Category browse and filter

- `GET /category/{slug}` — products in one category, same card component.
- Category nav in the header / a sidebar rail on the catalog page, with an
  active state.
- Category filter composes with search (`/search?q=…&category=…`).
- Tests: category page contents; search-plus-category intersection.

**Accept:** a shopper can narrow the catalog to one category and search inside it.

---

## Phase 8 — Cart: add and view

- `Cart`, `CartItem` models. Anonymous cart via a signed `session_token` cookie.
- Quantity picker on the detail page (`components/qty_picker.html`).
- `POST /cart/add` → HTMX fragment updating the header cart count.
- `GET /cart` → line items, per-line totals, subtotal.
- Tests: add creates a line; adding the same product again sums quantity; the
  cart page shows the right subtotal.

**Accept:** add a product from its detail page and see it on `/cart` with the
right subtotal.

---

## Phase 9 — Cart: change quantity, remove, subtotal

- `POST /cart/update` (quantity; 0 removes) and `POST /cart/remove`, both
  returning HTMX fragments that re-render the line and the subtotal.
- Empty-cart state. "Proceed to Checkout" present but explicitly inert, per
  [mission.md](./mission.md).
- Money maths verified in integer cents.
- Tests: update recomputes subtotal; remove drops the line; 0 quantity removes;
  negative/garbage quantity rejected.

**Accept:** every cart operation works and the subtotal is always correct.

---

## Phase 10 — Cart persistence hardening

- Cart survives navigation and a hard refresh for an anonymous visitor —
  verified on the deployed app, not just locally.
- Cookie is httpOnly, signed, `Secure` in production, with a sane lifetime;
  tampering is rejected rather than crashing.
- A stale or unknown cart token issues a fresh empty cart.
- Tests: cart contents across sequential requests; tampered cookie handled.

**Accept:** fill a cart on the live URL, close the tab, reopen the site — the
cart is still there.

---

## Phase 11 — Authentication

- `User` model, `app/security.py` with bcrypt hashing and session helpers.
- `GET/POST /signup`, `GET/POST /signin`, `POST /signout`, Amazon-styled forms.
- Header reflects auth state ("Hello, sign in" vs the user's name).
- Validation: email format, duplicate email, password length, wrong password —
  all with visible errors.
- Tests: signup → signin → signout; duplicate email; bad password.

**Accept:** a stranger can sign up on the live URL, sign out, and sign back in —
and the account still exists after a redeploy.

---

## Phase 12 — Cart ↔ account merge

The two halves meet.

- On sign in, merge the anonymous cart into the user's cart (sum quantities for
  the same product, delete the anonymous cart).
- On sign out, clear the session; the user's cart stays with the account.
- Tests: anonymous items appear after signin; overlapping products sum once;
  signin → signout → signin returns the same cart.

**Accept:** add items while signed out, sign in, and nothing is lost or doubled.

---

## Phase 13 — Polish and hardening

- Visual pass against `amazon_screenshots/`: spacing, header density, CTA
  colour, star rendering, price typography.
- Error pages: a styled 404 and 500 rather than raw tracebacks; debug output off
  in production.

**Accept:** the deployed app looks and behaves like a finished product on a laptop.

---

## Phase 14 — Documentation and final verification

- `README.md`: what it is, the live link, local setup, seed, run, test, the
  deployment story, and an explicit "what is out of scope" section pointing at
  [mission.md](./mission.md). Notes the free-tier cold start honestly.
- **Signed-out stranger check:** private window, fresh email, the full journey
  from landing page to a persisted cart, on the live URL.
- Full test suite green; `ruff check` clean; the deployed revision matches `main`.

**Accept:** a stranger with only the live link can shop the site end to end
without help, and a developer with only the README can run it locally — both
verified by actually doing it rather than assuming it.

---

## Deliberately not on this roadmap

Checkout and payment, orders, review authoring, recommendations, wish lists,
Prime, coupons, sellers, inventory, shipping. See
[mission.md](./mission.md#explicitly-out-of-scope).

## If time runs short

Drop whole phases, never half-finish one. A shipped feature that works is worth
more than two that almost do — and a half-built feature is worse than an absent
one, because a shopper will try it.

Order of what goes first: Phase 13 polish depth, then Phase 12's cart merge (an
anonymous cart that persists is still a working cart), then Phase 11 auth.
Phases 1–10 are the product: a live storefront that browses, searches, filters
and carts correctly is a real thing people can use, with or without accounts.
