"""The catalog listings: the landing page, search, and category browse.

All three screens read the catalog through the query builder below and render through
the same card component, so a product looks and behaves the same whether a shopper found
it by scrolling, by asking for it, or by narrowing to one shelf. They are also the same
query: browsing a category is a catalog listing with a category filter, and searching
inside a category is that filter with search terms on top, which is why
`/search?q=...&category=...` composes rather than being a fourth code path.
"""

from collections.abc import Sequence

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import Select, Text, cast, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db import DbSession
from app.models import Category, Product
from app.nav import NAV_ALL, shell
from app.templating import templates

router = APIRouter()

# A search box is a text field on a public URL, so the input is bounded before it
# reaches the database rather than trusted to be sensible. Both limits are far past any
# real product name -- the longest seeded title is about 120 characters -- so a shopper
# never meets them, while a hand-built URL with a megabyte of terms in it cannot turn
# one request into thousands of LIKE clauses.
MAX_QUERY_LENGTH = 120
MAX_QUERY_TERMS = 8


def catalog_query(category: Category | None = None) -> Select[tuple[Product]]:
    """The base catalog query every product listing starts from.

    The eager loads are not an optimisation detail: a card reads `primary_image`, so a
    lazy relationship would turn one page into one query per tile. Order is the category
    order from the seed file, then title -- deterministic, so the grid does not reshuffle
    between two requests or two backends. The join to `Category` is here rather than in
    the search filter because the order clause needs it either way, which also means
    search can match on the category name without joining the table twice.

    Passing `category` narrows the listing to one shelf. It filters on the foreign key
    rather than on the joined slug: the caller has already resolved the slug to a row, so
    matching the id is both cheaper and immune to a second row ever sharing the name.
    """
    statement = (
        select(Product)
        .join(Product.category)
        .options(selectinload(Product.images), joinedload(Product.category))
        .order_by(Category.position, Product.title)
    )
    if category is not None:
        statement = statement.where(Product.category_id == category.id)
    return statement


def list_products(db: Session, category: Category | None = None) -> Sequence[Product]:
    """Every product, in catalog order, with everything a card needs already loaded."""
    return db.scalars(catalog_query(category)).all()


def get_category(db: Session, slug: str) -> Category | None:
    """One category by its public slug, or `None` if there is no such shelf."""
    return db.scalars(select(Category).where(Category.slug == slug)).one_or_none()


def _contains(term: str) -> str:
    """Turn a search term into a LIKE pattern that matches it literally.

    Without this, `%` in a query would match every product and `_` would match any
    single character: the shopper's text would be read as pattern syntax instead of as
    the thing they are looking for. The backslash escapes are paired with
    `escape="\\"` at every call site below.
    """
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _matching(statement: Select, query: str) -> Select:
    """Add one AND condition per search term to any statement that joins both tables.

    Factored out so the results and the per-category counts under them are the same
    search by construction, not by two pieces of code agreeing. A count that disagreed
    with the page it is a filter for would be worse than no count at all.
    """
    for term in query[:MAX_QUERY_LENGTH].split()[:MAX_QUERY_TERMS]:
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
    return statement


def search_products(
    db: Session, query: str, category: Category | None = None
) -> Sequence[Product]:
    """Products matching every word of `query`, in the same order as the catalog.

    Each term has to appear *somewhere* on the product -- title, description, one of the
    key-info bullets, or the name of its category -- and every term has to match for the
    product to be a result. AND across terms, OR across fields: that is what makes
    "fire stick" find the Fire TV Stick while "fire blender" finds nothing, which is the
    answer a shopper expects from two words rather than the 30 products that mention
    either one.

    `category`, when given, is one more condition of the same AND: the results are the
    intersection of "matches these words" and "sits on this shelf". A blank query with a
    category is therefore the category page's list, which is what makes the header search
    box safe to leave scoped while a shopper clears it.

    A blank query is not an error and not an empty result: it is a question nobody
    asked, so it returns the full catalog.

    `ilike` is case-insensitive on both backends -- SQLAlchemy renders it as `ILIKE` on
    Postgres and as `lower(...) LIKE lower(...)` on SQLite. Substring matching means a
    partial word hits too ("blend" finds "Blender"), which is worth more on a catalog of
    this size than a stemmer or a full-text index would be. The trade is that there is
    no relevance ranking: results come back in catalog order, so the same search always
    returns the same page in the same sequence.
    """
    return db.scalars(_matching(catalog_query(category), query)).all()


def search_counts_by_category(db: Session, query: str) -> dict[str, int]:
    """How many products `query` matches on each shelf, keyed by category slug.

    One grouped query rather than one query per category: the refine row is drawn on
    every search, and six extra round trips to render six links is a bill that grows
    with the nav. Shelves with no match are absent from the mapping rather than present
    as zero, which is what lets the template offer only the filters that lead somewhere.
    """
    statement = _matching(
        select(Category.slug, func.count(Product.id))
        .join(Product, Product.category_id == Category.id)
        .group_by(Category.slug),
        query,
    )
    return dict(db.execute(statement).all())


@router.get("/")
async def home(request: Request, db: DbSession):
    """The storefront's front door."""
    return templates.TemplateResponse(
        request,
        "home.html",
        {"products": list_products(db)} | shell(db, nav_active=NAV_ALL),
    )


@router.get("/category/{slug}")
async def category_page(request: Request, db: DbSession, slug: str):
    """One shelf of the catalog, rendered as the same grid of the same cards."""
    category = get_category(db, slug)
    if category is None:
        # Same treatment as an unknown product slug, and for the same reason: a stale or
        # mistyped link should land a shopper on the site with a way back to the catalog,
        # not on a JSON error body. The slug is not echoed -- it is attacker-supplied
        # text, and there is nothing useful to say about it beyond that it is not a shelf.
        raise HTTPException(status_code=404, detail="We could not find that category.")

    return templates.TemplateResponse(
        request,
        "category.html",
        {
            "category": category,
            "products": list_products(db, category),
        }
        # The search box is scoped to this shelf while a shopper is standing in front of
        # it, so typing into it searches here rather than starting over.
        | shell(db, nav_active=category.slug, search_category=category),
    )


@router.get("/search")
async def search(
    request: Request,
    db: DbSession,
    # Declared with a default so `/search` with no query string is a valid request that
    # shows the catalog, not a 422. A shopper who submits the header form with an empty
    # box gets exactly that.
    q: str = Query("", description="What to search the catalog for."),
    category: str = Query("", description="Slug of the one category to search inside."),
):
    """Search results, optionally narrowed to one category."""
    query = q.strip()
    slug = category.strip()
    shelf = get_category(db, slug) if slug else None
    # A filter naming a category that does not exist is a bad URL, not a failed search:
    # a bookmark kept past a catalog reshuffle, or a hand-edited query string. The search
    # still answers, across the whole catalog, and the page says so -- the same call
    # product detail makes for an out-of-range `?image=`. Dropping the filter can only
    # widen the results, never point them at the wrong shelf.
    unknown_filter = bool(slug) and shelf is None

    return templates.TemplateResponse(
        request,
        "search.html",
        {
            "query": query,
            # Echoed into the header's search box so the field still holds what was
            # searched for after the page reloads -- a shopper refining a search edits
            # their words instead of retyping them.
            "search_query": query,
            "unknown_filter": unknown_filter,
            "products": search_products(db, query, shelf),
            # Drives the refine-by-category row under the heading. A count per shelf is
            # what makes the row worth showing: it is the difference between offering six
            # filters and offering the two that have anything behind them, so a shopper
            # never clicks through to an empty page.
            "match_counts": search_counts_by_category(db, query),
        }
        | shell(db, nav_active=shelf.slug if shelf else None, search_category=shelf),
    )
