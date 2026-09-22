"""Phase 3: the catalog exists in the database, and re-seeding it is safe.

The seed runs on every container start, so the tests that matter most here are not
"does it load the data" but "does the second run leave the data alone" and "does a bad
catalog file get refused before anything is written".
"""

import copy
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, Category, Product, ProductImage
from seed.seed import STATIC_DIR, SeedError, load_catalog, seed

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def catalog() -> dict:
    """The real committed catalog file -- the thing production actually seeds."""
    return load_catalog()


@pytest.fixture
def db(tmp_path) -> Session:
    """An empty database of its own, created from the models, for one test."""
    engine = create_engine(f"sqlite:///{tmp_path / 'seed-test.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def snapshot(session: Session) -> list[tuple]:
    """Every field the catalog owns, in a stable order, for before/after comparison."""
    return [
        (
            product.id,
            product.slug,
            product.title,
            product.description,
            tuple(product.key_info),
            product.price_cents,
            product.rating,
            product.rating_count,
            product.category.slug,
            tuple((image.position, image.path) for image in product.images),
        )
        for product in session.query(Product).order_by(Product.slug).all()
    ]


# --- loading the committed catalog ------------------------------------------------


def test_the_committed_catalog_file_is_valid(catalog):
    """If this fails, the deploy's start command fails and the site does not come up."""
    assert len(catalog["categories"]) >= 6
    assert 40 <= len(catalog["products"]) <= 60


def test_seed_populates_an_empty_database(db, catalog):
    report = seed(db, copy.deepcopy(catalog))
    db.commit()

    assert report.changed
    assert db.query(Category).count() == len(catalog["categories"])
    assert db.query(Product).count() == len(catalog["products"])
    assert db.query(ProductImage).count() == sum(len(p["images"]) for p in catalog["products"])


def test_every_product_has_a_category_and_at_least_one_image(db, catalog):
    """A product card cannot render without either, so neither is allowed to be absent."""
    seed(db, copy.deepcopy(catalog))
    db.commit()

    for product in db.query(Product).all():
        assert product.category is not None, product.slug
        assert len(product.images) >= 1, product.slug
        assert product.primary_image.position == 1, product.slug


def test_every_category_has_products(db, catalog):
    """An empty category is a dead link in the nav that Phase 7 will add."""
    seed(db, copy.deepcopy(catalog))
    db.commit()

    for category in db.query(Category).all():
        assert category.products, category.slug


def test_gallery_positions_are_contiguous_and_start_at_one(db, catalog):
    seed(db, copy.deepcopy(catalog))
    db.commit()

    for product in db.query(Product).all():
        positions = [image.position for image in product.images]
        assert positions == list(range(1, len(positions) + 1)), product.slug


def test_prices_are_positive_integer_cents_and_ratings_are_in_range(db, catalog):
    seed(db, copy.deepcopy(catalog))
    db.commit()

    for product in db.query(Product).all():
        assert isinstance(product.price_cents, int) and product.price_cents > 0, product.slug
        assert 0 <= product.rating <= 5, product.slug
        assert product.rating_count >= 0, product.slug


def test_every_catalog_image_exists_on_disk(catalog):
    """The catalog may only point at image files that are actually committed."""
    for product in catalog["products"]:
        for relative_path in product["images"]:
            assert (STATIC_DIR / relative_path).is_file(), relative_path


# --- idempotency and convergence --------------------------------------------------


def test_re_running_the_seed_changes_nothing(db, catalog):
    """The whole reason the seed is safe in the container's start command."""
    seed(db, copy.deepcopy(catalog))
    db.commit()
    before = snapshot(db)

    second = seed(db, copy.deepcopy(catalog))
    db.commit()

    assert not second.changed
    assert second.summary() == "catalog already up to date -- nothing changed"
    # Ids included: a row must be left alone, not deleted and recreated identically.
    assert snapshot(db) == before


def test_a_third_run_also_changes_nothing(db, catalog):
    """Guards against a seed that converges on the second run but oscillates after."""
    for _ in range(2):
        seed(db, copy.deepcopy(catalog))
        db.commit()
    before = snapshot(db)

    assert not seed(db, copy.deepcopy(catalog)).changed
    db.commit()
    assert snapshot(db) == before


def test_an_edited_field_is_updated_in_place(db, catalog):
    seed(db, copy.deepcopy(catalog))
    db.commit()
    slug = catalog["products"][0]["slug"]
    original_id = db.query(Product).filter_by(slug=slug).one().id

    edited = copy.deepcopy(catalog)
    edited["products"][0]["price_cents"] = 12345
    edited["products"][0]["title"] = "A retitled product"
    report = seed(db, edited)
    db.commit()

    assert report.updated == [slug]
    product = db.query(Product).filter_by(slug=slug).one()
    assert product.id == original_id
    assert (product.price_cents, product.title) == (12345, "A retitled product")


def test_a_product_dropped_from_the_file_is_removed(db, catalog):
    """products.json is the source of truth, so a deletion has to propagate."""
    seed(db, copy.deepcopy(catalog))
    db.commit()

    pruned = copy.deepcopy(catalog)
    dropped = pruned["products"].pop()
    report = seed(db, pruned)
    db.commit()

    assert report.deleted == [dropped["slug"]]
    assert db.query(Product).filter_by(slug=dropped["slug"]).one_or_none() is None
    assert db.query(Product).count() == len(catalog["products"]) - 1
    # The images went with it rather than being left orphaned.
    assert db.query(ProductImage).count() == sum(
        len(p["images"]) for p in catalog["products"] if p["slug"] != dropped["slug"]
    )


def test_a_shrunk_gallery_drops_the_trailing_image(db, catalog):
    multi_image = next(p for p in catalog["products"] if len(p["images"]) > 1)
    seed(db, copy.deepcopy(catalog))
    db.commit()

    shrunk = copy.deepcopy(catalog)
    entry = next(p for p in shrunk["products"] if p["slug"] == multi_image["slug"])
    entry["images"] = entry["images"][:1]
    report = seed(db, shrunk)
    db.commit()

    assert report.updated == [multi_image["slug"]]
    product = db.query(Product).filter_by(slug=multi_image["slug"]).one()
    assert [image.path for image in product.images] == entry["images"]


def test_a_category_dropped_from_the_file_takes_its_products_with_it(db, catalog):
    seed(db, copy.deepcopy(catalog))
    db.commit()

    pruned = copy.deepcopy(catalog)
    dropped = pruned["categories"].pop()
    pruned["products"] = [p for p in pruned["products"] if p["category"] != dropped["slug"]]
    seed(db, pruned)
    db.commit()

    assert db.query(Category).filter_by(slug=dropped["slug"]).one_or_none() is None
    assert db.query(Product).count() == len(pruned["products"])


def test_seeding_an_existing_database_from_scratch_is_not_a_conflict(db, catalog):
    """A restart against a populated database is the ordinary case, not the exception."""
    seed(db, copy.deepcopy(catalog))
    db.commit()
    db.expire_all()

    assert not seed(db, copy.deepcopy(catalog)).changed


# --- refusing a bad catalog file --------------------------------------------------


def write_catalog(tmp_path: Path, catalog: dict) -> Path:
    path = tmp_path / "products.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    return path


def test_a_missing_catalog_file_is_a_clear_error(tmp_path):
    with pytest.raises(SeedError, match="not found"):
        load_catalog(tmp_path / "absent.json")


def test_malformed_json_is_a_clear_error(tmp_path):
    path = tmp_path / "products.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SeedError, match="not valid JSON"):
        load_catalog(path)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ({"price_cents": 0}, "positive integer"),
        ({"price_cents": -100}, "positive integer"),
        ({"price_cents": 19.99}, "positive integer"),
        ({"price_cents": True}, "positive integer"),
        ({"rating": 7}, "between 0 and 5"),
        ({"rating": -1}, "between 0 and 5"),
        ({"rating": "4.5"}, "must be a number"),
        ({"rating_count": -3}, "non-negative integer"),
        ({"title": ""}, "non-empty string"),
        ({"description": "   "}, "non-empty string"),
        ({"key_info": []}, "non-empty list"),
        ({"key_info": ["fine", ""]}, "non-empty string"),
        ({"images": []}, "at least one path"),
        ({"category": "no-such-category"}, "unknown category"),
    ],
)
def test_a_corrupt_product_is_refused(tmp_path, catalog, mutation, expected):
    broken = copy.deepcopy(catalog)
    broken["products"][0].update(mutation)
    with pytest.raises(SeedError, match=expected):
        load_catalog(write_catalog(tmp_path, broken))


def test_a_duplicate_product_slug_is_refused(tmp_path, catalog):
    broken = copy.deepcopy(catalog)
    broken["products"].append(copy.deepcopy(broken["products"][0]))
    with pytest.raises(SeedError, match="duplicate product slug"):
        load_catalog(write_catalog(tmp_path, broken))


def test_a_duplicate_category_slug_is_refused(tmp_path, catalog):
    broken = copy.deepcopy(catalog)
    broken["categories"].append(copy.deepcopy(broken["categories"][0]))
    with pytest.raises(SeedError, match="duplicate category slug"):
        load_catalog(write_catalog(tmp_path, broken))


def test_a_duplicate_image_path_within_one_product_is_refused(tmp_path, catalog):
    broken = copy.deepcopy(catalog)
    first = broken["products"][0]["images"][0]
    broken["products"][0]["images"] = [first, first]
    with pytest.raises(SeedError, match="duplicate path"):
        load_catalog(write_catalog(tmp_path, broken))


def test_an_image_path_with_no_file_behind_it_is_refused(tmp_path, catalog):
    """Rather than seeding a catalog whose landing page shows broken images."""
    broken = copy.deepcopy(catalog)
    broken["products"][0]["images"] = ["products/does-not-exist.svg"]
    with pytest.raises(SeedError, match="image file is missing"):
        load_catalog(write_catalog(tmp_path, broken))


@pytest.mark.parametrize("empty", [{}, {"categories": [], "products": []}])
def test_an_empty_catalog_is_refused(tmp_path, empty):
    with pytest.raises(SeedError, match="non-empty"):
        load_catalog(write_catalog(tmp_path, empty))


def test_a_refused_catalog_writes_nothing(db, catalog, tmp_path):
    """Validation happens in full before the first row, so a bad file is inert."""
    seed(db, copy.deepcopy(catalog))
    db.commit()
    before = snapshot(db)

    broken = copy.deepcopy(catalog)
    broken["products"][0]["price_cents"] = -1
    with pytest.raises(SeedError):
        seed(db, load_catalog(write_catalog(tmp_path, broken)))

    assert snapshot(db) == before


# --- the deploy runs it ------------------------------------------------------------


def test_the_container_seeds_before_it_serves():
    """A deploy that starts uvicorn without seeding serves an empty storefront."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    assert "COPY seed seed" in dockerfile
    assert "python -m seed.seed && exec uvicorn" in dockerfile
