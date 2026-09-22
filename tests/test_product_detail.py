"""Phase 5: the product detail page, reached from any tile, and the 404 behind a bad slug.

The assertions run against the committed catalog rather than invented fixtures, so what
is checked is the page a shopper actually gets on the live site.
"""

import html
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import get_db
from app.main import app
from app.models import Base, Category, Product, ProductImage


@pytest.fixture
def one_image_client(tmp_path, catalog) -> TestClient:
    """A client whose database holds one product with a gallery of exactly one image."""
    engine = create_engine(f"sqlite:///{tmp_path / 'one-image.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    session = session_factory()
    session.add(
        Product(
            slug="lonely-product",
            title="A product with exactly one image",
            description="One image is a valid gallery.",
            key_info=["Has exactly one image"],
            price_cents=1999,
            rating=4.0,
            rating_count=1,
            category=Category(slug="oddments", name="Oddments", position=1),
            # A path that is really on disk, so the rendered page is not a broken image.
            images=[ProductImage(path=catalog["products"][0]["images"][0], position=1)],
        )
    )
    session.commit()
    session.close()

    def one_image_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = one_image_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


@pytest.fixture
def product(catalog) -> dict:
    """A product with more than one image, so the gallery has something to switch."""
    return next(p for p in catalog["products"] if len(p["images"]) > 1)


@pytest.fixture
def page(client, product) -> str:
    """The rendered detail page for that product, with HTML entities decoded."""
    response = client.get(f"/product/{product['slug']}")
    assert response.status_code == 200
    return html.unescape(response.text)


# --- the page shows everything the catalog knows -----------------------------------


def test_every_seeded_product_has_a_detail_page(client, catalog):
    """A tile links to every one of these, so every one of them has to answer."""
    for entry in catalog["products"]:
        response = client.get(f"/product/{entry['slug']}")
        assert response.status_code == 200, entry["slug"]
        assert html.unescape(entry["title"]) in html.unescape(response.text), entry["slug"]


def test_the_title_is_the_page_heading_and_the_document_title(page, product):
    assert f'<h1 class="mt-1 text-[24px] font-normal leading-8">{product["title"]}</h1>' in page
    assert "<title>" in page


def test_the_price_comes_from_the_stored_cents(page, product):
    cents = product["price_cents"]
    assert f"${cents // 100:,}.{cents % 100:02d}" in page


def test_the_rating_and_its_count_are_both_shown(page, product):
    label = f"{product['rating']:.1f} out of 5 stars, {product['rating_count']:,} ratings"
    assert label in page


def test_the_description_and_every_key_info_bullet_are_shown(page, product):
    assert product["description"] in page
    assert "About this item" in page
    for point in product["key_info"]:
        assert f"<li>{point}</li>" in page


def test_the_category_is_named(page, product, catalog):
    name = next(c["name"] for c in catalog["categories"] if c["slug"] == product["category"])
    assert name in page


def test_the_page_does_not_claim_anything_the_catalog_cannot_back_up(page):
    """No invented stock, delivery or seller. A storefront that makes those up is lying."""
    for invention in ("In Stock", "Free delivery", "Ships from", "Sold by", "FREE Returns"):
        assert invention not in page


# --- the gallery -------------------------------------------------------------------


def test_the_gallery_shows_the_first_image_by_default(page, product):
    assert f'/static/{product["images"][0]}"' in page


def test_every_image_has_a_thumbnail_linking_to_its_own_view(page, product):
    for position in range(2, len(product["images"]) + 1):
        assert f'href="/product/{product["slug"]}?image={position}"' in page
    # The selected thumbnail is state, not a control, so it does not link to itself.
    assert f'href="/product/{product["slug"]}?image=1"' not in page
    assert 'aria-current="true"' in page


def test_asking_for_a_later_image_shows_that_image(client, product):
    body = client.get(f"/product/{product['slug']}?image=2").text
    assert f'alt="{html.escape(product["title"])} — image 2 of {len(product["images"])}"' in body
    # ...and the first image's thumbnail becomes a link again now that it is not current.
    assert f'href="/product/{product["slug"]}?image=1"' in body


@pytest.mark.parametrize("bogus", ["0", "-3", "99", "2.5", "banana", ""])
def test_a_bogus_image_parameter_still_shows_the_product(client, product, bogus):
    """A bad query string is a bad URL, not a missing product -- show image one."""
    response = client.get(f"/product/{product['slug']}?image={bogus}")
    assert response.status_code == 200
    assert f'/static/{product["images"][0]}"' in response.text


def test_a_single_image_product_gets_no_thumbnail_rail(one_image_client, catalog):
    """A rail of one thumbnail is a control with nothing to switch to.

    Every seeded product has more than one image, so this state is built rather than
    found: the model allows a gallery of one, so the page has to render one properly.
    """
    response = one_image_client.get("/product/lonely-product")
    assert response.status_code == 200
    assert 'aria-label="Product images"' not in response.text
    # The one image is still shown, and without the "image 1 of 1" that would be noise.
    assert f'/static/{catalog["products"][0]["images"][0]}"' in response.text
    assert 'alt="A product with exactly one image"' in response.text


def test_the_large_image_is_labelled_and_the_thumbnails_are_not(page, product):
    """Duplicating the title on every thumbnail would read as the same product n times."""
    alts = re.findall(r'<img[^>]*alt="([^"]*)"', page)
    assert [alt for alt in alts if alt.strip()] == [
        f"{product['title']} — image 1 of {len(product['images'])}"
    ]


# --- getting there, and not getting there ------------------------------------------


def test_a_tile_on_the_landing_page_links_to_the_detail_page(client, catalog):
    """The roadmap's acceptance check: clicking any tile opens a detail page."""
    body = client.get("/").text
    for entry in catalog["products"]:
        assert f'href="/product/{entry["slug"]}"' in body, entry["slug"]


def test_an_unknown_slug_is_a_404_page_and_not_a_traceback(client):
    response = client.get("/product/no-such-product")
    assert response.status_code == 404
    assert "text/html" in response.headers["content-type"]
    assert "We could not find that product." in response.text
    # A dead end that only apologises is still a dead end.
    assert 'href="/"' in response.text


def test_an_unknown_slug_is_not_echoed_back_into_the_page(client):
    """An unknown slug is attacker-supplied text; the page has nothing to say about it."""
    response = client.get("/product/<script>alert(1)</script>")
    assert response.status_code == 404
    assert "<script>alert" not in response.text


def test_an_unknown_page_gets_the_same_styled_404(client):
    response = client.get("/no-such-page")
    assert response.status_code == 404
    assert "We could not find that page." in response.text


def test_the_buy_box_says_the_cart_is_not_built_yet(page):
    """Phase 8 builds it. Until then it is visibly inert rather than absent or fake."""
    assert "Quantity selection and Add to Cart arrive in a later build." in page
    assert 'action="/cart/add"' not in page


def test_the_detail_page_survives_an_empty_catalog(empty_client, product):
    """The route has to 404 rather than 500 when the product genuinely is not there."""
    assert empty_client.get(f"/product/{product['slug']}").status_code == 404
