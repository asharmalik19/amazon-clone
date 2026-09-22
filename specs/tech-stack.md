# Tech Stack

The stack is chosen to be small, boring, and fully local. No build step, no
package registry for front-end assets, no external database service, no network
access required at runtime.

## Decisions

| Layer | Choice |
| --- | --- |
| Language | Python 3.12+ |
| Web framework | FastAPI |
| Templating | Jinja2 (server-rendered HTML) |
| Interactivity | HTMX (partial swaps), tiny vanilla JS only where HTMX cannot do it |
| Styling | Tailwind CSS via CDN |
| Database (local) | SQLite — a file, zero setup |
| Database (production) | Managed Postgres (`psycopg`) — survives redeploys |
| ORM | SQLAlchemy 2.x (declarative, typed) — one model layer, two backends |
| Migrations | None — schema created from models, data from the seed script |
| Auth | Session cookie (signed, httpOnly), `bcrypt` password hashing |
| Server | Uvicorn |
| Hosting | Render — Docker web service, auto-deploy on push to `main` |
| Tests | pytest + `httpx`/FastAPI `TestClient` |
| Dependency management | `pyproject.toml` + `uv` (fall back to `pip` + venv) |
| Lint / format | `ruff` (lint + format) |

## Why

- **FastAPI + Jinja2**, not a JS SPA: the journey in
  [mission.md](./mission.md) is mostly navigation and forms. Server rendering
  gets us correct, fast, linkable pages with no client-side state machine.
- **HTMX**, not React: the only genuinely dynamic moments are add-to-cart,
  quantity changes, and cart line removal. Each is "POST, then swap a fragment"
  — exactly HTMX's shape. It keeps one source of truth (the server).
- **Tailwind via CDN**, not a build pipeline: Amazon's look is dense utility
  layout, which Tailwind expresses directly. The CDN keeps `npm` out of the repo
  entirely. Accepted trade-off: a CDN-sized stylesheet and a flash-free-render
  requirement handled by keeping critical layout simple. If this becomes a
  problem, the escape hatch is the Tailwind CLI producing one static CSS file —
  no template changes needed.
- **SQLite locally, Postgres in production**: SQLite means anyone can clone the
  repo and run the app with no database service at all. But Render's filesystem is ephemeral — on
  every redeploy a SQLite file would be wiped, taking every signup and cart with
  it. Production therefore points `DATABASE_URL` at managed Postgres. SQLAlchemy
  makes this a URL swap, and the test suite runs against both.
- **Session cookies**, not JWT: we need sign in / sign out with server-side
  truth. Cookies are the simpler and safer default for a server-rendered app.
  The session cookie and the cart cookie are signed by the same HMAC helper in
  `app/security.py` — one implementation, one reject path, so the two cannot end
  up trusting different things.
- **`bcrypt` directly, not `passlib[bcrypt]`** (changed in Phase 11): passlib
  has had no release since 2019 and its bcrypt backend raises against bcrypt
  4.x, so the wrapper is now a liability rather than a convenience. All this app
  asks of it is one hash and one verify, which `bcrypt` exposes itself.

## Project shape

```
app/
  main.py            # FastAPI app, startup, static + template wiring
  config.py          # settings (DB URL, secret key) from env with defaults
  db.py              # engine, SessionLocal, get_db dependency
  models.py          # Product, Category, ProductImage, User, Cart, CartItem
  security.py        # password hashing, session helpers, current_user
  routers/
    catalog.py       # landing page, category browse, search
    product.py       # product detail page
    cart.py          # add / view / update quantity / remove
    auth.py          # sign up, sign in, sign out
  templates/
    base.html        # header (logo, search, nav, cart count), footer
    components/      # product_card.html, stars.html, price.html, qty_picker.html
    ...page templates, plus fragments/ for HTMX partial responses
  static/
    products/        # local product images
seed/
  products.json      # catalog seed data
  seed.py            # loads products.json into the DB (idempotent)
  make_placeholders.py  # generates the local placeholder product images
tests/
specs/
amazon_screenshots/  # visual reference, not shipped
Dockerfile           # single image used locally and on Render
render.yaml          # Render service + Postgres, infrastructure as code
.dockerignore
```

## Data model (intended)

- `Category` — id, slug, name.
- `Product` — id, slug, title, description, key-info bullets, price in **integer
  cents**, rating (0–5, one decimal), rating_count, category_id.
- `ProductImage` — id, product_id, path, position. A product has 1..n images so
  the detail page can show a gallery.
- `User` — id, email (normalized, unique), name, password_hash, created_at.
- `Cart` — id, user_id (nullable), session_token (nullable), created_at.
- `CartItem` — id, cart_id, product_id, quantity. Unique on (cart_id, product_id).

Money is stored and computed in integer cents and only formatted at render time.
No float arithmetic on prices, anywhere.

## Catalog data source

Product data is **derived from the reference screenshots** in
`amazon_screenshots/`: real titles, prices, and ratings transcribed into
`seed/products.json`, grouped into a handful of categories. Images are local
placeholder files under `app/static/products/` — we do not hotlink or
redistribute Amazon's images. Descriptions and key-info bullets are written by
us in the style of the reference.

The seed is committed, deterministic, and re-runnable. `seed/products.json` is
the single source of catalog truth; nothing is fetched at runtime.

## Cart persistence rules

- An anonymous visitor gets a cart keyed by an opaque `session_token` cookie.
  This is what makes the cart survive navigation and refresh without an account.
- On sign in, the anonymous cart is merged into the user's cart: quantities for
  the same product are summed, then the anonymous cart is deleted.
- On sign out, the session cookie is cleared; the user's cart stays with the
  account.

## Deployment

A publicly reachable app is part of the product, so deployment is treated as
infrastructure that exists from the second phase onward — not as a final step.

- **One image everywhere.** A single `Dockerfile` runs the app locally and on
  Render. If it works in the container on a laptop, it works in production.
- **`render.yaml`.** The web service and the Postgres instance are declared in
  the repo, so the deploy is reproducible and reviewable rather than a sequence
  of clicks someone has to remember.
- **Auto-deploy on push to `main`.** Every phase after Phase 2 lands on the live
  URL as a side effect of being committed. There is never an un-deployed backlog.
- **Start command:** run the idempotent seed, then `uvicorn` bound to
  `0.0.0.0:$PORT`. Because the seed is idempotent, a restart is always safe.
- **Configuration by environment**, with local defaults:

  | Variable | Local default | Production |
  | --- | --- | --- |
  | `DATABASE_URL` | `sqlite:///./app.db` | Postgres URL from Render |
  | `SECRET_KEY` | obvious dev-only literal | generated secret, set in Render |
  | `PORT` | `8000` | supplied by Render |

- **Health check** at `GET /healthz` returning 200, so Render can tell a booting
  container from a broken one.
- **Cold starts.** Render's free tier sleeps after ~15 minutes idle and takes
  30–50s to wake. For a product meant to be used by strangers, a 40-second blank
  screen is a real defect, not a footnote — a first-time visitor will assume the
  site is broken and leave. Mitigation, in order of preference: an external
  uptime pinger hitting `/healthz` every ~10 minutes to keep the instance warm;
  failing that, the paid always-on tier. The README states the tier's behaviour
  plainly either way.
- **Verified as a stranger.** The live URL is opened in a private window, signed
  out, and taken through the whole journey. It has to work for someone who is
  not us, on a machine that is not ours.

## Non-negotiables

- No feature outside the journey in [mission.md](./mission.md).
- No external network calls at runtime (the Tailwind and HTMX CDN tags in
  `base.html` are the only exception, and both must be swappable for vendored
  files).
- No secrets in the repo. `SECRET_KEY` comes from the environment with a
  development-only default that is obviously a development default; the
  production value is set in Render and never committed. Same for
  `DATABASE_URL`.
- No personal or employer-identifying contact details in the repo, the deployed
  app, or the hosting config.
- Every page works without JavaScript for the read paths; HTMX enhances the
  write paths.
- `ruff check` and `pytest` pass before any phase is called done — and from
  Phase 2 onward, the phase is not done until it is **live on the deployed
  URL**.
