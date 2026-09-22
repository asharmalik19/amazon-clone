"""The landing page: the catalog as a grid of product cards.

Search and category browse land here too, in Phases 6 and 7, reading from the same
catalog query and rendering through the same card component.
"""

from collections.abc import Sequence

from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db import DbSession
from app.models import Category, Product
from app.templating import templates

router = APIRouter()


def list_products(db: Session) -> Sequence[Product]:
    """Every product, in catalog order, with everything a card needs already loaded.

    The eager loads are not an optimisation detail: a card reads `primary_image`, so a
    lazy relationship would turn one page into one query per tile. Order is the category
    order from the seed file, then title -- deterministic, so the grid does not reshuffle
    between two requests or two backends.
    """
    statement = (
        select(Product)
        .join(Product.category)
        .options(selectinload(Product.images), joinedload(Product.category))
        .order_by(Category.position, Product.title)
    )
    return db.scalars(statement).all()


@router.get("/")
async def home(request: Request, db: DbSession):
    """The storefront's front door."""
    return templates.TemplateResponse(request, "home.html", {"products": list_products(db)})
