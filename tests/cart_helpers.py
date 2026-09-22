"""Helpers shared by the cart test modules.

Phase 8 tests adding and reading the cart; Phase 9 tests editing it. Both drive the same
HTTP surface with the same cookie jar and assert against the same rendered markup, so the
request shapes and the price formatting live here rather than being copied between the
two files -- if the cart page's markup changes, one helper changes with it.
"""

import html
import re


def add(client, slug, quantity=1, htmx=False):
    """Post an add-to-cart the way the rendered form does."""
    return post(client, "/cart/add", {"slug": slug, "quantity": str(quantity)}, htmx=htmx)


def update(client, slug, quantity, htmx=False):
    """Post a quantity change the way the cart line's form does."""
    return post(client, "/cart/update", {"slug": slug, "quantity": str(quantity)}, htmx=htmx)


def remove(client, slug, htmx=False):
    """Post a line removal the way the Delete button does."""
    return post(client, "/cart/remove", {"slug": slug}, htmx=htmx)


def post(client, path, data, htmx=False):
    """A cart write, as either an HTMX request or a plain browser form post."""
    return client.post(
        path,
        data=data,
        headers={"HX-Request": "true"} if htmx else {},
        # The no-JS path answers with a 303; following it here would hide the status
        # under the cart page's 200, and the redirect is the thing under test.
        follow_redirects=False,
    )


def cart_page(client) -> str:
    """The cart page's HTML, with entities decoded so titles can be matched as written."""
    response = client.get("/cart")
    assert response.status_code == 200
    return html.unescape(response.text)


def money(cents: int) -> str:
    """Cents formatted the way `components/price.html` renders them for a screen reader."""
    return f"${cents // 100:,}.{cents % 100:02d}"


def line_totals(page: str) -> list[str]:
    """Every price on the page, in order, as the accessible text of the price macro."""
    return re.findall(r'<span class="sr-only">(\$[\d,]+\.\d\d)</span>', page)


def line_slugs(page: str) -> list[str]:
    """The slug of every cart line on the page, in the order they are rendered."""
    return re.findall(r'<li id="cart-line-([^"]+)"', page)


def quantity_of(page: str, slug: str) -> int | None:
    """The quantity `slug`'s line shows, read from its picker's selected option.

    `None` when there is no line for that product, which is how the tests tell "removed"
    apart from "set to something".
    """
    line = re.search(rf'<li id="cart-line-{re.escape(slug)}".*?</li>', page, re.DOTALL)
    if line is None:
        return None
    selected = re.search(r'<option value="(\d+)" selected>', line.group(0))
    assert selected is not None, f"the line for {slug} has no selected quantity"
    return int(selected.group(1))
