# amazonia

An Amazon-inspired storefront covering one thing properly: the primary shopping
journey, from landing page to a filled cart. See [specs/mission.md](specs/mission.md)
for scope, [specs/tech-stack.md](specs/tech-stack.md) for how, and
[specs/roadmap.md](specs/roadmap.md) for the order things get built in.

## Current state

**Phase 1 — walking skeleton.** The app boots and serves the shared page shell.
The catalog, search, category nav and cart are not built yet, so those header
controls are rendered visibly inert rather than as controls that do nothing.

## Local setup

```sh
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
```

(Or `python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"`.)

## Run

```sh
.venv/bin/uvicorn app.main:app --reload
```

Then open <http://127.0.0.1:8000>. `GET /healthz` returns `{"status": "ok"}`.

## Test and lint

```sh
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

## Configuration

All settings come from the environment with local-development defaults
(see `app/config.py`).

| Variable | Local default |
| --- | --- |
| `DATABASE_URL` | `sqlite:///./app.db` |
| `SECRET_KEY` | an obvious dev-only literal |
| `PORT` | `8000` |

## Out of scope

Checkout and payment, orders, reviews, recommendations, wish lists, Prime,
coupons, sellers, inventory and shipping. The full list is in
[specs/mission.md](specs/mission.md#explicitly-out-of-scope).
