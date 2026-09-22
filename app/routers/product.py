"""The product detail page: one product, in full.

This is the screen a shopper evaluates a product on, so everything the catalog knows
about a product is shown here and nothing is invented. There is no "in stock", no
delivery estimate and no seller -- the app does not know any of that, and a storefront
that makes it up is lying to the person reading it.

The gallery is addressed by a query parameter rather than by script, so picking an image
is a plain link a browser can follow with JavaScript switched off (see
specs/tech-stack.md -- read paths work without JS; HTMX enhances the write paths).
"""

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db import DbSession
from app.models import Product
from app.templating import templates

router = APIRouter()


def get_product(db: Session, slug: str) -> Product | None:
    """One product by its public slug, with its gallery and category already loaded.

    Slug, not id: the URL is part of the product's identity, so re-seeding cannot
    silently repoint a link a shopper has bookmarked or shared.
    """
    statement = (
        select(Product)
        .where(Product.slug == slug)
        .options(selectinload(Product.images), joinedload(Product.category))
    )
    return db.scalars(statement).one_or_none()


@router.get("/product/{slug}")
async def product_detail(
    request: Request,
    db: DbSession,
    slug: str,
    # Taken as text and parsed here rather than declared as an `int`, which would make
    # `?image=banana` a 422 validation error. A shopper who lands on a hand-edited or
    # truncated URL should see the product, not a framework error page: the query
    # parameter chooses a view, and an unreadable choice just means the default one.
    # 1-based, to match the positions a person is shown in "image 2 of 3".
    image: str = Query("1", description="Which gallery image to show, 1-based."),
):
    """One product's detail page, showing the `image`-th gallery image."""
    product = get_product(db, slug)
    if product is None:
        # The slug is not echoed back into the page: an unknown slug is attacker-supplied
        # text, and there is nothing useful to say about it beyond that it is not a
        # product. The 404 page offers the catalog instead of a dead end.
        raise HTTPException(status_code=404, detail="We could not find that product.")

    # A bogus `?image=` is a bad URL, not a missing product, so it shows the product with
    # its first image rather than a 404. Clamping rather than erroring also means an
    # out-of-date link from a gallery that has since shrunk keeps working.
    try:
        requested = int(image)
    except ValueError:
        requested = 1
    selected = min(max(requested, 1), len(product.images))

    return templates.TemplateResponse(
        request,
        "product_detail.html",
        {"product": product, "selected_image": selected},
    )
