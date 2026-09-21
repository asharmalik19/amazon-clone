# Mission

## What we are building

An Amazon.com clone focused on a single thing: **the primary customer shopping
journey**, from landing on the site to holding a filled cart.

> Land → browse or search → open a product → add it to the cart → review the cart.

This is not an attempt to reproduce Amazon's feature surface. It is an attempt to
reproduce the *spine* of Amazon, well, with an interface that is recognisably
Amazon-inspired.

## This is a real product

It is not a demo, a mockup, or something assembled to pass an inspection. It is
a working storefront that a stranger can land on and actually use. That sets the
bar for everything below:

- **Every feature in scope works properly**, not just along the happy path a
  demo would follow. Real users type nonsense into search, refresh mid-flow,
  open two tabs, arrive on a phone, hit the back button, and submit forms twice.
- **No dead ends and no lies.** Every state has a real screen — empty cart, no
  search results, unknown product, wrong password. Nothing is a placeholder that
  looks live.
- **Speed comes from narrow scope, not from low quality.** We ship fast by
  building *few* things, and each of those things is finished. Cutting corners
  inside a feature is not speed; it is debt with a shorter fuse.
- **It stays up.** Data survives restarts and redeploys. Someone who signs up
  today still has an account tomorrow.

## Who it is for

A shopper who opens the site cold — no account, no instructions, no idea who
built it — and should be able to find a product they want and get it into a cart
without being taught anything.

## The journey we own

| Step | What the user does | What we must provide |
| --- | --- | --- |
| 1 | Arrives on the site | Amazon-inspired landing page with a browsable catalog |
| 2 | Scans products | Image, title, price, rating on every product tile |
| 3 | Narrows down | Search by product name / relevant product info |
| 4 | Narrows down | Browse and filter by category |
| 5 | Evaluates one product | Product detail page: images, title, price, rating, description / key info, quantity selection, Add to Cart |
| 6 | Builds a basket | Add to cart, view cart, change quantity, remove items, see subtotal |
| 7 | Persists | Cart survives navigation and refresh |
| 8 | Has an identity | Sign up, sign in, sign out |

Everything in this table is in scope. Nothing outside it is.

## Explicitly out of scope

Prime / membership, Alexa, gift cards, coupons and promotions, seller
functionality, writing customer reviews, a recommendation engine, order history
and tracking, wish lists, customer service, real inventory management, complex
shipping and fulfillment, payment processing, and Amazon's full
category/navigation hierarchy.

Checkout is out of scope. The cart may show a **Proceed to Checkout** button for
UI completeness; it does not lead to real payment, shipping, or fulfillment.

## Product principle

> When deciding whether to add functionality, prioritize features that directly
> support the primary shopping journey. Features outside that journey are not
> added unless they complete the core experience.

Applied as a test for any proposed change:

1. Does it sit on a step of the journey above? If no, it does not get built.
2. Would a first-time user be blocked or confused without it? If no, defer it.
3. Can it be done with the existing data model and stack? If no, say so out loud
   before building it.

"It would be cool if" is not a reason. "A shopper cannot complete step N without
it" is.

## Design intent

- **Recognisably Amazon.** Dense product grids, the dark utility header with the
  search bar as the widest element on the page, orange/yellow call-to-action
  buttons, star ratings with a review count, prices rendered with a large whole
  part and a small superscript cents part. The reference material lives in
  `amazon_screenshots/`.
- **Fast and server-rendered.** Pages come back complete. Interactivity is added
  where it earns its keep (quantity, add to cart, cart updates), not everywhere.
- **Honest.** Nothing in the UI promises behaviour we have not built. If an
  action is a stub, it looks like a stub is acceptable — we do not fake success
  states for out-of-scope features.

## Definition of done

The app is done when a shopper who has never seen it before can, unaided:

- land on the home page and see a catalog of products with image, title, price
  and rating;
- search for a product by name and get sensible matching results, shown with the
  same product presentation used everywhere else;
- filter the catalog to a category;
- open a product detail page, read the key information, pick a quantity, and add
  it to the cart;
- see the cart with correct line items and subtotal, change a quantity, remove a
  line, and refresh the page without losing any of it;
- sign up, sign out, and sign back in.

...and do it without hitting a broken state along the way. Anything beyond that
list is a bonus and is subject to the product principle.

They must be able to do all of it **on a public URL, in a private browser
window, with no account on our machine**. A journey that only works on localhost
is not done — a deployed, publicly reachable app is part of the product, not a
step after it. Deployment therefore lands in
[Phase 2](./roadmap.md#phase-2--deploy-the-skeleton), while the app is still a
header and a placeholder.

See [tech-stack.md](./tech-stack.md) for how, and [roadmap.md](./roadmap.md) for
the order.
