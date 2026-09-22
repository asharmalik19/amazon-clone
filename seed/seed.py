"""Load `products.json` into the database. Idempotent, re-runnable, both backends.

    python -m seed.seed

This runs on every container start, so three properties are not optional:

1. **Idempotent.** A second run against an already-seeded database must change nothing
   and must say so. That is what makes it safe in the start command -- a restart loop
   cannot corrupt or duplicate the catalog.
2. **Convergent.** `products.json` is the source of truth, so a row the file no longer
   describes is removed, not left behind. Otherwise a product deleted from the file
   would haunt production forever while looking correct locally.
3. **All or nothing.** The file is validated in full before a single row is written, and
   the writes share one transaction. A malformed seed file leaves the catalog exactly as
   it was rather than half-replaced.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db import create_schema, get_engine, get_sessionmaker
from app.models import Category, Product, ProductImage

CATALOG_PATH = Path(__file__).resolve().parent / "products.json"
# Image paths in the catalog are relative to the static mount; this is where those files
# actually live, so the seed can refuse to point the catalog at an image that is missing.
STATIC_DIR = Path(__file__).resolve().parent.parent / "app" / "static"

logger = logging.getLogger("amazonia.seed")

MAX_RATING = 5.0


class SeedError(Exception):
    """The catalog file is unusable. Raised before anything is written."""


@dataclass
class SeedReport:
    """What one seed run did. Printed at the end so a deploy log is readable."""

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.created or self.updated or self.deleted)

    def summary(self) -> str:
        if not self.changed:
            return "catalog already up to date -- nothing changed"
        return (
            f"catalog written: {len(self.created)} created, "
            f"{len(self.updated)} updated, {len(self.deleted)} removed"
        )


def load_catalog(path: Path = CATALOG_PATH, *, check_images: bool = True) -> dict[str, Any]:
    """Read and validate the catalog file, raising `SeedError` on anything unusable.

    `check_images=False` skips the on-disk image check. Only the placeholder generator
    passes it, because its job is to create the files that check looks for.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SeedError(f"catalog file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SeedError(f"catalog file is not valid JSON ({path}): {exc}") from exc

    categories = raw.get("categories")
    products = raw.get("products")
    if not isinstance(categories, list) or not categories:
        raise SeedError("catalog file needs a non-empty 'categories' list")
    if not isinstance(products, list) or not products:
        raise SeedError("catalog file needs a non-empty 'products' list")

    _validate_categories(categories)
    _validate_products(
        products,
        known_categories={c["slug"] for c in categories},
        check_images=check_images,
    )
    return {"categories": categories, "products": products}


def _validate_categories(categories: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for index, category in enumerate(categories):
        where = f"categories[{index}]"
        for key in ("slug", "name"):
            if not isinstance(category.get(key), str) or not category[key].strip():
                raise SeedError(f"{where}: '{key}' must be a non-empty string")
        if category["slug"] in seen:
            raise SeedError(f"{where}: duplicate category slug {category['slug']!r}")
        seen.add(category["slug"])


def _validate_products(
    products: list[dict[str, Any]],
    known_categories: set[str],
    *,
    check_images: bool = True,
) -> None:
    seen: set[str] = set()
    for index, product in enumerate(products):
        where = f"products[{index}]"
        for key in ("slug", "title", "description", "category"):
            if not isinstance(product.get(key), str) or not product[key].strip():
                raise SeedError(f"{where}: '{key}' must be a non-empty string")
        slug = product["slug"]
        if slug in seen:
            raise SeedError(f"{where}: duplicate product slug {slug!r}")
        seen.add(slug)

        if product["category"] not in known_categories:
            raise SeedError(f"{where} ({slug}): unknown category {product['category']!r}")

        price = product.get("price_cents")
        # `bool` is an `int` in Python, and `True` as a price would pass a naive check.
        if not isinstance(price, int) or isinstance(price, bool) or price <= 0:
            raise SeedError(f"{where} ({slug}): 'price_cents' must be a positive integer")

        rating = product.get("rating")
        if not isinstance(rating, int | float) or isinstance(rating, bool):
            raise SeedError(f"{where} ({slug}): 'rating' must be a number")
        if not 0 <= rating <= MAX_RATING:
            raise SeedError(f"{where} ({slug}): 'rating' must be between 0 and {MAX_RATING}")

        count = product.get("rating_count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise SeedError(f"{where} ({slug}): 'rating_count' must be a non-negative integer")

        key_info = product.get("key_info")
        if not isinstance(key_info, list) or not key_info:
            raise SeedError(f"{where} ({slug}): 'key_info' must be a non-empty list")
        if not all(isinstance(bullet, str) and bullet.strip() for bullet in key_info):
            raise SeedError(f"{where} ({slug}): every 'key_info' bullet must be a non-empty string")

        images = product.get("images")
        # A product card cannot render without an image, so a product without one is a
        # broken tile on the landing page rather than a tolerable gap in the data.
        if not isinstance(images, list) or not images:
            raise SeedError(f"{where} ({slug}): 'images' must list at least one path")
        if len(set(images)) != len(images):
            raise SeedError(f"{where} ({slug}): 'images' contains a duplicate path")
        for path in images:
            if not isinstance(path, str) or not path.strip():
                raise SeedError(f"{where} ({slug}): every image path must be a non-empty string")
            if check_images and not (STATIC_DIR / path).is_file():
                raise SeedError(
                    f"{where} ({slug}): image file is missing: app/static/{path}. "
                    "Run `python -m seed.make_placeholders` to generate it."
                )


def _seed_categories(
    session: Session, categories: list[dict[str, Any]], report: SeedReport
) -> None:
    existing = {category.slug: category for category in session.query(Category).all()}

    for position, entry in enumerate(categories, start=1):
        # Position defaults to the file's own order, so the nav order is whatever the
        # catalog file reads like -- one obvious place to change it.
        wanted_position = entry.get("position", position)
        category = existing.get(entry["slug"])
        if category is None:
            session.add(Category(slug=entry["slug"], name=entry["name"], position=wanted_position))
            report.created.append(f"category {entry['slug']}")
            continue
        if (category.name, category.position) != (entry["name"], wanted_position):
            category.name = entry["name"]
            category.position = wanted_position
            report.updated.append(f"category {entry['slug']}")

    wanted = {entry["slug"] for entry in categories}
    for slug, category in existing.items():
        if slug not in wanted:
            # Cascades to the category's products and their images: a shelf that the
            # catalog file no longer describes takes its contents with it.
            session.delete(category)
            report.deleted.append(f"category {slug}")

    # Flush so the products pass can look categories up by id, including new ones.
    session.flush()


def _seed_products(session: Session, products: list[dict[str, Any]], report: SeedReport) -> None:
    categories = {category.slug: category for category in session.query(Category).all()}
    existing = {product.slug: product for product in session.query(Product).all()}

    for entry in products:
        product = existing.get(entry["slug"])
        category = categories[entry["category"]]
        if product is None:
            product = Product(slug=entry["slug"])
            session.add(product)
            _apply_product_fields(product, entry, category)
            _apply_images(product, entry["images"])
            report.created.append(entry["slug"])
            continue

        fields_changed = _apply_product_fields(product, entry, category)
        images_changed = _apply_images(product, entry["images"])
        if fields_changed or images_changed:
            report.updated.append(entry["slug"])

    wanted = {entry["slug"] for entry in products}
    for slug, product in existing.items():
        if slug not in wanted:
            session.delete(product)
            report.deleted.append(slug)


def _apply_product_fields(product: Product, entry: dict[str, Any], category: Category) -> bool:
    """Copy the catalog entry onto `product`. Returns True if anything actually changed."""
    wanted = {
        "title": entry["title"],
        "description": entry["description"],
        "key_info": list(entry["key_info"]),
        "price_cents": entry["price_cents"],
        "rating": float(entry["rating"]),
        "rating_count": entry["rating_count"],
        "category_id": category.id,
    }
    changed = False
    for name, value in wanted.items():
        if getattr(product, name, None) != value:
            setattr(product, name, value)
            changed = True
    return changed


def _apply_images(product: Product, paths: list[str]) -> bool:
    """Make the product's gallery match `paths` exactly, in order. Returns True if changed."""
    existing = {image.position: image for image in product.images}
    changed = False

    for position, path in enumerate(paths, start=1):
        image = existing.pop(position, None)
        if image is None:
            product.images.append(ProductImage(path=path, position=position))
            changed = True
        elif image.path != path:
            image.path = path
            changed = True

    # Whatever is left held a position the catalog no longer uses -- a gallery that
    # shrank from three images to two. `delete-orphan` on the relationship turns the
    # collection removal into a DELETE, so no explicit session call is needed.
    for image in existing.values():
        product.images.remove(image)
        changed = True

    return changed


def seed(session: Session, catalog: dict[str, Any] | None = None) -> SeedReport:
    """Bring `session`'s database in line with the catalog file. Does not commit."""
    catalog = catalog if catalog is not None else load_catalog()
    report = SeedReport()
    _seed_categories(session, catalog["categories"], report)
    _seed_products(session, catalog["products"], report)
    return report


def main(argv: list[str] | None = None) -> int:
    """Entry point for `python -m seed.seed`, and for the container's start command."""
    parser = argparse.ArgumentParser(description="Load the catalog into the database.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the catalog file and report what would change, writing nothing.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(message)s")

    try:
        catalog = load_catalog()
    except SeedError as exc:
        # The start command runs this before uvicorn, so a non-zero exit here is the
        # deploy failing loudly instead of the site coming up with an empty catalog.
        logger.error("seed refused to run: %s", exc)
        return 1

    if args.check:
        logger.info(
            "catalog file is valid: %d categories, %d products",
            len(catalog["categories"]),
            len(catalog["products"]),
        )
        return 0

    create_schema()
    session = get_sessionmaker()()
    try:
        report = seed(session, catalog)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        get_engine().dispose()

    logger.info("%s (%s)", report.summary(), get_engine().dialect.name)
    for slug in report.deleted:
        logger.info("removed %s -- no longer in products.json", slug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
