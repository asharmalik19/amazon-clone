"""Phase 4: the landing page renders the seeded catalog as a grid of product cards.

The card component is the only way a product is ever rendered, so what is checked here
is what every later screen inherits: the title, the image, the rating, and a price
formatted from integer cents.
"""

import html
import re

import pytest

from app.templating import templates


@pytest.fixture
def body(client) -> str:
    """The rendered landing page, with HTML entities decoded.

    Titles carry ampersands, which Jinja escapes on the way out. Decoding here keeps the
    assertions about what a shopper reads rather than about entity encoding.
    """
    return html.unescape(client.get("/").text)


def test_the_landing_page_lists_every_seeded_product(body, catalog):
    for product in catalog["products"]:
        assert product["title"] in body, product["slug"]


def test_one_card_per_product(body, catalog):
    assert body.count("<article") == len(catalog["products"])


def test_every_card_shows_its_first_image_and_only_that_one(body, catalog):
    """The card is a tile, not a gallery: the rest of the images belong to Phase 5."""
    for product in catalog["products"]:
        primary, *rest = product["images"]
        assert f'/static/{primary}"' in body, product["slug"]
        for extra in rest:
            assert extra not in body, product["slug"]


def test_every_product_image_has_the_product_title_as_alt_text(body, catalog):
    """A product image with no alt text is an unlabelled link target for a screen reader."""
    alts = re.findall(r'<img[^>]*alt="([^"]*)"', body)
    assert len(alts) == len(catalog["products"])
    assert all(alt.strip() for alt in alts)


def test_prices_render_as_dollars_and_cents_from_integer_cents(body, catalog):
    """The visible price has to match the stored cents exactly -- no rounding, no floats."""
    for product in catalog["products"]:
        cents = product["price_cents"]
        expected = f"${cents // 100:,}.{cents % 100:02d}"
        assert expected in body, f"{product['slug']} -> {expected}"


def test_ratings_render_as_an_accessible_sentence(body, catalog):
    for product in catalog["products"]:
        label = f"{product['rating']:.1f} out of 5 stars, {product['rating_count']:,} ratings"
        assert label in body, product["slug"]


def test_a_partial_rating_is_drawn_as_a_partial_star_row():
    """4.6 is neither four stars nor five, and the width is how that is told truthfully."""
    stars = templates.get_template("components/stars.html").module.stars
    assert "width: 92.0%" in stars(4.6, 10)
    assert "width: 100.0%" in stars(5.0, 10)


def test_the_grid_is_responsive(body):
    """A dense grid on a laptop, two columns on a phone -- the roadmap's acceptance check."""
    assert "grid-cols-2" in body
    assert "xl:grid-cols-5" in body


def test_cards_do_not_link_anywhere_yet(body):
    """The detail page is Phase 5. Until it exists, no tile may offer a link to it."""
    assert "/product/" not in body


def test_an_empty_catalog_gets_an_empty_state_not_a_blank_page(empty_client):
    response = empty_client.get("/")
    assert response.status_code == 200
    assert "The catalog is empty" in response.text
    assert "<article" not in response.text
