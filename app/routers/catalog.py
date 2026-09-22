"""The landing page and search: the catalog as a grid of product cards.

Both screens read the catalog through the query builder below and render through the
same card component, so a product looks and behaves the same whether a shopper found it
by scrolling or by asking for it. Category browse joins them in Phase 7.
"""

from collections.abc import Sequence

from fastapi import APIRouter, Query, Request
from sqlalchemy import Select, Text, cast, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db import DbSession
from app.models import Category, Product
from app.templating import templates

router = APIRouter()

# A search box is a text field on a public URL, so the input is bounded before it
# reaches the database rather than trusted to be sensible. Both limits are far past any
# real product name -- the longest seeded title is about 120 characters -- so a shopper
# never meets them, while a hand-built URL with a megabyte of terms in it cannot turn
# one request into thousands of LIKE clauses.
MAX_QUERY_LENGTH = 120
MAX_QUERY_TERMS = 8


def catalog_query() -> Select[tuple[Product]]:
    """The base catalog query every product listing starts from.

    The eager loads are not an optimisation detail: a card reads `primary_image`, so a
    lazy relationship would turn one page into one query per tile. Order is the category
    order from the seed file, then title -- deterministic, so the grid does not reshuffle
    between two requests or two backends. The join to `Category` is here rather than in
    the search filter because the order clause needs it either way, which also means
    search can match on the category name without joining the table twice.
    """
    return (
        select(Product)
        .join(Product.category)
        .options(selectinload(Product.images), joinedload(Product.category))
        .order_by(Category.position, Product.title)
    )


def list_products(db: Session) -> Sequence[Product]:
    """Every product, in catalog order, with everything a card needs already loaded."""
    return db.scalars(catalog_query()).all()


def _contains(term: str) -> str:
    """Turn a search term into a LIKE pattern that matches it literally.

    Without this, `%` in a query would match every product and `_` would match any
    single character: the shopper's text would be read as pattern syntax instead of as
    the thing they are looking for. The backslash escapes are paired with
    `escape="\\"` at every call site below.
    """
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_products(db: Session, query: str) -> Sequence[Product]:
    """Products matching every word of `query`, in the same order as the catalog.

    Each term has to appear *somewhere* on the product -- title, description, one of the
    key-info bullets, or the name of its category -- and every term has to match for the
    product to be a result. AND across terms, OR across fields: that is what makes
    "fire stick" find the Fire TV Stick while "fire blender" finds nothing, which is the
    answer a shopper expects from two words rather than the 30 products that mention
    either one.

    A blank query is not an error and not an empty result: it is a question nobody
    asked, so it returns the full catalog.

    `ilike` is case-insensitive on both backends -- SQLAlchemy renders it as `ILIKE` on
    Postgres and as `lower(...) LIKE lower(...)` on SQLite. Substring matching means a
    partial word hits too ("blend" finds "Blender"), which is worth more on a catalog of
    this size than a stemmer or a full-text index would be. The trade is that there is
    no relevance ranking: results come back in catalog order, so the same search always
    returns the same page in the same sequence.
    """
    terms = query[:MAX_QUERY_LENGTH].split()[:MAX_QUERY_TERMS]
    statement = catalog_query()
    for term in terms:
        pattern = _contains(term)
        statement = statement.where(
            or_(
                Product.title.ilike(pattern, escape="\\"),
                Product.description.ilike(pattern, escape="\\"),
                # `key_info` is a JSON array of strings, which neither backend can be
                # asked to search element by element in portable SQL. Casting the column
                # to text and matching the serialised array is the one move that means
                # the same thing on SQLite and Postgres. The cost is that a term made of
                # JSON punctuation could match the delimiters rather than a bullet --
                # harmless for a shopper searching for words, and the alternative is a
                # separate table for data that is only ever read as an ordered list.
                cast(Product.key_info, Text).ilike(pattern, escape="\\"),
                Category.name.ilike(pattern, escape="\\"),
            )
        )
    return db.scalars(statement).all()


@router.get("/")
async def home(request: Request, db: DbSession):
    """The storefront's front door."""
    return templates.TemplateResponse(request, "home.html", {"products": list_products(db)})


@router.get("/search")
async def search(
    request: Request,
    db: DbSession,
    # Declared with a default so `/search` with no query string is a valid request that
    # shows the catalog, not a 422. A shopper who submits the header form with an empty
    # box gets exactly that.
    q: str = Query("", description="What to search the catalog for."),
):
    """Search results, rendered with the same card component as the landing page."""
    query = q.strip()
    return templates.TemplateResponse(
        request,
        "search.html",
        {
            "query": query,
            # Echoed into the header's search box so the field still holds what was
            # searched for after the page reloads -- a shopper refining a search edits
            # their words instead of retyping them.
            "search_query": query,
            "products": search_products(db, query),
        },
    )
