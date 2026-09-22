# amazonia

An Amazon-inspired storefront covering one thing properly: the primary shopping
journey, from landing page to a filled cart. See [specs/mission.md](specs/mission.md)
for scope, [specs/tech-stack.md](specs/tech-stack.md) for how, and
[specs/roadmap.md](specs/roadmap.md) for the order things get built in.

## Live URL

<https://amazonia-jpu0.onrender.com>

Free instance: the first request after 15 minutes of inactivity waits about a
minute while the service wakes up. See [Deployment](#deployment).

## Current state

**Phase 12 — the cart and the account are one thing.** Fill a cart as a stranger,
sign in, and it is still there. Fill one and create an account instead, and it
survives that too — filling a basket and *then* deciding to register is the
likeliest order anyone does this in, and a signup that quietly emptied the cart
it started from would be the worst moment in the app to lose one.

Nothing is doubled either, which is the harder half. A product sitting in both
carts comes out on one line with the quantities added, not twice at two prices,
because the merge goes through the same summing an ordinary second add does. A
merged line may hold more than the ten one add allows — ten in the account plus
ten in the browser is a shopper who wants twenty — and the picker shows twenty
rather than quietly clamping it.

Signing in *consumes* the anonymous cart rather than copying it: the row is
either adopted outright (its `user_id` set, its token cleared, its line order and
age intact) or emptied into the account's cart and deleted, and the cart cookie
is dropped on the way in. So a cart is findable by an account or by a cookie,
never by both, and there is exactly one answer to whose cart a request is looking
at. Signing out is the deliberate opposite: it ends the session and leaves the
cart with the account, so the browser goes back to being a stranger's with an
empty cart — which is the honest thing for a shared machine to show the next
person, and it is waiting at the next sign-in.

Before it, **Phase 11 — accounts.** A stranger can create one from the header: name, email,
password, and the password again, because a password typed blind is a password
worth typing twice. Signing up signs you in, the header stops saying "Hello,
sign in" and starts saying your name, and Sign out is a button in a real form
rather than a link — a sign-out a link could trigger is one any other site's
`<img>` tag can trigger for you.

Nothing about the forms is silent. A duplicate email, an address with no `@`, a
password under 8 characters, one bcrypt would quietly truncate at 72 bytes, a
mistyped confirmation, a missing name: each comes back as the same form with the
message against the field it belongs to, every problem at once rather than one
per submission, and with what was typed still in the fields — except the
passwords, which are never echoed back into a page. Sign in is the deliberate
exception: a wrong password and an unknown address get one identical message and
the same half-second of hashing, because anything else turns the form into a way
to find out who has an account here.

Passwords are stored as bcrypt hashes and nothing else, so the database holds no
password to steal. The session is one signed, httpOnly cookie carrying a user id
and the moment it was issued, verified by the same HMAC helper the cart cookie
uses — forged, truncated, expired, re-signed with a rotated key, or naming an
account that no longer exists, every one of them is a signed-out visitor rather
than an error page or somebody else's session. The window is checked on the
server, because `Max-Age` is a request to the browser and the browser is the one
party we cannot make keep it.

Before that, **Phase 10 — a cart that is still there tomorrow.** The cart is held by one
signed, httpOnly cookie, and this phase is about that cookie holding up. It
carries a 30-day lifetime, refreshed by every add, so closing the tab no longer
throws the cart away and a basket in weekly use never ages out — while a
forgotten one still does. It is sent `Secure` on the deployed site (declared in
`render.yaml`, and inferred from `SECRET_KEY` if a deploy forgets to say so) and
deliberately not over plain HTTP locally, because a browser drops a `Secure`
cookie on an insecure connection without telling anyone.

Everything else about it is about not trusting it. The value is an opaque random
token plus an HMAC of that token, compared in constant time as bytes — so a
`Cookie` header of arbitrary bytes, which is what an attacker actually gets to
send, is a mismatch rather than a crash. Forged, truncated, re-signed, stale or
signed with a rotated key: every one of them looks exactly like a first visit,
which is an empty cart and no error page. Reads still write nothing at all — no
cart row, no cookie — and only an add may bring either into existence.

Before that again, **Phase 9 — the cart a shopper can change their mind in.** Picking a
quantity on a product page adds it to a cart held, for a stranger, by a signed,
httpOnly cookie; no
cookie and no cart row exist until that first add, so browsing leaves no trace.
`/cart` lists what is in it with per-line totals and a subtotal, and each line
carries the two controls that make a cart a cart: a quantity picker (`0` deletes)
and Delete. Both are real forms — with JavaScript they swap the cart contents and
the header badge in place, without it they post and land back on `/cart` with the
change applied. Removing the last line returns the same empty state a first-time
visitor sees, from the same component, so the two cannot drift.

Money never leaves integer cents: a line total is `price_cents × quantity`, the
subtotal is the sum of those, and the only division is the one that puts the dot
in the rendered price. A quantity the picker cannot produce is refused rather than
guessed at, an edit to a product that is not in the cart changes nothing instead
of erroring, and an edit sent with no cookie creates no cart. **Proceed to
Checkout** is rendered visibly disabled and says why: checkout is out of scope for
this project, permanently.

Before that, **Phase 7 — category browse and filter.** The category bar under the header is
drawn from the database, so it lists every shelf the catalog actually has and
nothing it does not. `/category/{slug}` shows one shelf in the same grid of the
same cards as the landing page, the bar marks where the shopper currently is,
and each product's detail page links back to the shelf it came off.

Browse and search compose rather than competing: `/search?q=…&category=…` is the
intersection of the two, so a shopper can narrow to Books and then search inside
it. Standing on a shelf scopes the header search box to it — visibly, with the
category named in the box, because a search that is quietly narrowed is a search
that lies about its results — and a "Refine by category" row under any results
offers the shelves that query actually hit, with a count each, so no filter leads
to an empty page. "All categories" is always one click away.

The states are real screens: an unknown category slug is a styled 404, a filter
that empties the results says which shelf it searched and how many matches are
waiting elsewhere, and a filter naming a category that no longer exists answers
across the whole catalog and says so rather than failing validation.

Before it: the header search box works on every page. `/search?q=…` matches
case-insensitively across a product's title, description, key-info bullets and
the name of its category, and every word of the query has to land somewhere on
the product for it to be a result — so "fire stick" finds the two Fire TV Sticks
rather than everything that mentions either word. Partial words match too
("avoca" finds the avocado), results come back in catalog order, no matches
shows what was searched for, an empty query shows everything, and wildcards a
shopper types are searched for literally — `%` finds the products that say
"100%", not all of them.

Every tile opens a full detail page at `/product/{slug}` with an image gallery
addressed by `?image=N` (so it works with JavaScript off and every view has its
own URL), the title, price, rating and count, description and the "About this
item" bullets — and nothing the catalog cannot back up, so no invented stock,
delivery date or seller. All 51 products sit in a responsive grid with prices
formatted from integer cents and partial ratings drawn as partial stars.

No control in the header is a placeholder any more — search, the category bar,
the cart and the account menu all do what they say. The app is live in a
container on Render backed by managed Postgres, so every phase reaches the live
URL just by being committed to `main`, and an account created today is still
there after the next deploy.

## Local setup

```sh
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
```

(Or `python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"`.)

## Seed the catalog

```sh
.venv/bin/python -m seed.seed
```

This creates the schema if it is absent and loads
[`seed/products.json`](seed/products.json) — the single source of catalog truth.
It is idempotent: running it again reports `catalog already up to date` and
writes nothing, which is why the container runs it on every start. It is also
convergent, so a product removed from the file is removed from the database.

`--check` validates the file and writes nothing. The product images are locally
generated SVG placeholders; regenerate them with
`.venv/bin/python -m seed.make_placeholders` (`--check` reports any that are
missing). No Amazon imagery is hotlinked or redistributed — see
[specs/tech-stack.md](specs/tech-stack.md#catalog-data-source) for where the
catalog data comes from.

## Run

```sh
.venv/bin/uvicorn app.main:app --reload
```

Then open <http://127.0.0.1:8000>. `GET /healthz` returns `{"status": "ok"}`.

### Run the container

The same image runs locally and in production:

```sh
docker build -t amazonia .
docker run --rm -p 8000:8000 amazonia
```

Pass `-e PORT=…` to change the port and `-e DATABASE_URL=…` to point it at
Postgres instead of the default SQLite file.

## Test and lint

```sh
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

## Configuration

All settings come from the environment with local-development defaults
(see `app/config.py`).

| Variable | Local default | Production |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./app.db` | Postgres URL, injected by Render |
| `SECRET_KEY` | an obvious dev-only literal | generated by Render, never committed |
| `PORT` | `8000` | supplied by Render |
| `COOKIE_SECURE` | unset → off | `true` in `render.yaml` |

`postgres://` and `postgresql://` URLs are rewritten to `postgresql+psycopg://`
on the way in, so a provider's connection string works unedited.

`COOKIE_SECURE` takes `true/1/yes/on` or `false/0/no/off`; unset, blank or
unrecognised means "nobody said", and the cart cookie then follows whether
`SECRET_KEY` came from the environment. Leave it off locally — a `Secure` cookie
over HTTP is silently dropped, and the cart looks broken for no visible reason.

## Deployment

The container's start command seeds and then serves: `python -m seed.seed &&
exec uvicorn …`. The seed is idempotent, so every restart re-runs it safely, and
the `&&` means a catalog that cannot be written fails the deploy instead of
bringing up an empty storefront.

Hosting is Render, declared as infrastructure in [`render.yaml`](render.yaml):
one Docker web service plus a managed Postgres instance, health-checked at
`/healthz`, auto-deploying on every commit to `main`. The live service was
created by applying that blueprint, so the repo and production describe the
same thing -- infra changes are a reviewed commit rather than a sequence of
dashboard clicks someone has to remember.

Production uses Postgres because Render's filesystem is ephemeral: a SQLite
file would be wiped on every redeploy, taking every signup and cart with it.
The blueprint injects `DATABASE_URL` from the database via `fromDatabase`, so
the connection string is never copied by hand or committed, and `SECRET_KEY` is
generated by Render.

To reproduce the deploy from scratch:

1. Push the repository to GitHub.
2. In Render, **New → Blueprint** and point it at the repository. It reads
   `render.yaml` and creates both the web service and the database, wiring
   `DATABASE_URL` and `SECRET_KEY` itself. Render asks for a card to verify the
   account; the free instance types it creates are not charged for.
3. Record the resulting `*.onrender.com` URL under "Live URL" above.

The app logs which backend it connected to and whether the URL came from the
environment, so a misconfigured deploy is one line in the log rather than a
guess. It refuses to start at all if the database is unreachable: a container
that cannot reach its database is broken, not slow, and should fail the health
check immediately instead of serving errors later.

**Free-tier behaviour, stated plainly:** the free web service spins down
after 15 minutes of inactivity and takes about a minute to spin back up, so a
first visit to a cold instance shows a loading page for that long. A free
Render Postgres instance also expires 30 days after creation. Keeping the
instance warm with an external pinger against `/healthz`, or moving to a paid
always-on instance, is the fix.

## Out of scope

Checkout and payment, orders, reviews, recommendations, wish lists, Prime,
coupons, sellers, inventory and shipping. The full list is in
[specs/mission.md](specs/mission.md#explicitly-out-of-scope).
