"""Generate the placeholder product images the catalog points at.

    python -m seed.make_placeholders            # write any missing file
    python -m seed.make_placeholders --force    # rewrite them all
    python -m seed.make_placeholders --check    # report missing files, write nothing

We do not hotlink or redistribute Amazon's product photography, so every image in this
storefront is a locally generated placeholder: an SVG tinted by category with the
product's initials and its position in the gallery. SVG rather than a raster format
because it is text -- it diffs, it compresses, it costs a few hundred bytes a file, and
it needs no image library in the dependency list.

Output is deterministic: the same catalog entry always produces byte-identical SVG, so
regenerating never shows up as noise in a diff. The generated files are committed, and
`seed.py` refuses to seed a catalog whose images are missing from disk.
"""

from __future__ import annotations

import argparse
import logging
import sys
from xml.sax.saxutils import escape

from seed.seed import STATIC_DIR, SeedError, load_catalog

logger = logging.getLogger("amazonia.placeholders")

# One tint per category, in the file's own order. Muted enough that a grid of them reads
# as product photography on a white page rather than as a colour chart.
TINTS: list[tuple[str, str, str]] = [
    ("#eef4fb", "#c9dcf0", "#1f4e79"),
    ("#fdf3ec", "#f3d9c4", "#8a4b1f"),
    ("#f2f1fa", "#d7d4ee", "#3f3a7a"),
    ("#eff7f0", "#cee6d2", "#1f5c33"),
    ("#fdf0f5", "#f2d2e0", "#7d2b50"),
    ("#fbf7ea", "#ecdfb8", "#6b5411"),
]


def monogram(title: str) -> str:
    """Up to two initials from the first words of a title that carry meaning."""
    skip = {"the", "a", "an", "of", "for", "and", "with", "in", "on", "to"}
    initials = [
        word[0].upper()
        for word in title.replace("-", " ").split()
        if word[0].isalnum() and word.lower().strip(",:|") not in skip
    ]
    return "".join(initials[:2]) or "AZ"


def render_svg(title: str, tint: tuple[str, str, str], position: int, total: int) -> str:
    """Return the SVG for one gallery slot. Pure function of its arguments."""
    background, accent, ink = tint
    label = f"{title} -- placeholder image {position} of {total}"
    # The gallery slot is drawn into the art itself, so an out-of-order or duplicated
    # image is visible on the page instead of being a silent data bug.
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 600" width="600" '
        f'height="600" role="img" aria-label="{escape(label, {chr(34): "&quot;"})}">\n'
        f'  <rect width="600" height="600" fill="{background}"/>\n'
        f'  <circle cx="300" cy="268" r="150" fill="{accent}"/>\n'
        f'  <text x="300" y="268" fill="{ink}" font-family="Helvetica, Arial, sans-serif" '
        'font-size="128" font-weight="700" text-anchor="middle" dominant-baseline="central"'
        f">{escape(monogram(title))}</text>\n"
        f'  <text x="300" y="486" fill="{ink}" font-family="Helvetica, Arial, sans-serif" '
        'font-size="26" text-anchor="middle" opacity="0.75"'
        f">view {position} of {total}</text>\n"
        "</svg>\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate placeholder product images.")
    parser.add_argument("--force", action="store_true", help="Rewrite files that already exist.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report any catalog image missing from disk and exit non-zero. Writes nothing.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(message)s")

    try:
        # Read the catalog without the image-file check, since generating those files is
        # the whole point of this script.
        catalog = load_catalog(check_images=False)
    except SeedError as exc:
        logger.error("cannot read the catalog: %s", exc)
        return 1

    tint_for_category = {
        entry["slug"]: TINTS[index % len(TINTS)]
        for index, entry in enumerate(catalog["categories"])
    }

    written = 0
    missing: list[str] = []
    for product in catalog["products"]:
        paths = product["images"]
        tint = tint_for_category[product["category"]]
        for position, relative_path in enumerate(paths, start=1):
            destination = STATIC_DIR / relative_path
            if args.check:
                if not destination.is_file():
                    missing.append(relative_path)
                continue
            if destination.is_file() and not args.force:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            svg = render_svg(product["title"], tint, position, len(paths))
            destination.write_text(svg, encoding="utf-8")
            written += 1

    if args.check:
        if missing:
            logger.error("%d catalog image(s) missing from disk:", len(missing))
            for relative_path in missing:
                logger.error("  app/static/%s", relative_path)
            return 1
        logger.info("every catalog image is present on disk")
        return 0

    logger.info("%d placeholder image(s) written to app/static/products/", written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
