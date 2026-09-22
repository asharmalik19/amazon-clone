"""The catalog schema: one model layer that runs on SQLite and Postgres alike.

Phase 3 owned the catalog -- `Category`, `Product`, `ProductImage` -- Phase 8 added the
cart that hangs off it, and Phase 11 brings `User`. Each table arrived with the phase
that actually uses it, so nothing here is a table waiting for a feature that may never
land.

Two conventions hold everywhere in this file:

- **Money is integer cents.** `price_cents` is the only price representation; it is
  divided for display and never for arithmetic. Floats are not used for money anywhere
  in this project.
- **`slug` is the public identity.** URLs and the seed both address rows by slug, not by
  the autoincrement id, so re-seeding cannot silently repoint a link.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    """Declarative base for every model in the app."""

    # `list[str]` is mapped to a JSON column rather than SQLAlchemy's default guess. It
    # is the same declaration on both backends: SQLite stores JSON as text, Postgres as
    # its native JSON type, and SQLAlchemy serialises identically either way.
    type_annotation_map = {list[str]: JSON}


class Category(Base):
    """A shelf of the catalog. Products belong to exactly one."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    # Explicit display order, so the header nav does not reorder itself when a product
    # is added or an id happens to be reused.
    position: Mapped[int] = mapped_column(Integer, default=0)

    products: Mapped[list[Product]] = relationship(
        back_populates="category",
        cascade="all, delete-orphan",
        order_by="Product.title",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Category {self.slug}>"


class Product(Base):
    """One item in the catalog, with everything both the card and the detail page need."""

    __tablename__ = "products"
    __table_args__ = (
        # A price of zero or a rating outside 0-5 is corrupt data, not an edge case. The
        # database is the last place that can still refuse it, so it does.
        CheckConstraint("price_cents > 0", name="ck_products_price_positive"),
        CheckConstraint("rating >= 0 AND rating <= 5", name="ck_products_rating_range"),
        CheckConstraint("rating_count >= 0", name="ck_products_rating_count_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    # The bulleted "About this item" block on the detail page. A list of strings is the
    # shape the template wants and the shape the seed provides; a separate table would
    # buy ordering guarantees we already get from JSON array order.
    key_info: Mapped[list[str]]
    price_cents: Mapped[int] = mapped_column(Integer)
    # Display data, not money: a star count is rendered, never summed, so a float is
    # safe here in a way it would never be for `price_cents`. Float rather than Numeric
    # deliberately -- SQLite has no native decimal type, and asking SQLAlchemy for one
    # buys a per-row conversion warning in exchange for precision nothing needs.
    rating: Mapped[float] = mapped_column(Float)
    rating_count: Mapped[int] = mapped_column(Integer)

    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    category: Mapped[Category] = relationship(back_populates="products")

    images: Mapped[list[ProductImage]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductImage.position",
    )

    @property
    def primary_image(self) -> ProductImage:
        """The image a product card shows. Every product is seeded with at least one."""
        return self.images[0]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Product {self.slug}>"


class ProductImage(Base):
    """One image of a product. A product has 1..n so the detail page can show a gallery."""

    __tablename__ = "product_images"
    __table_args__ = (
        # Two images claiming the same slot would make the gallery order arbitrary.
        UniqueConstraint("product_id", "position", name="uq_product_image_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    # Relative to the static mount -- e.g. "products/owala-freesip-1.svg". Stored without
    # the "/static/" prefix so the mount point can move without a data migration.
    path: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer)

    product: Mapped[Product] = relationship(back_populates="images")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ProductImage {self.path}>"


class User(Base):
    """One shopper with an account.

    The table arrives with Phase 11, the phase that actually signs people in, rather
    than having sat empty since Phase 3. What it holds is the minimum an account needs
    to exist: a name to greet them by, an email to find them by, and a hash to check
    them against.

    There is no password column and never will be -- `password_hash` holds a bcrypt
    digest produced by `app.security`, so the plaintext a shopper typed exists only for
    the length of one request and a stolen database yields no passwords.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # `email` is the public identity: it is what a shopper signs in with, so it is
    # stored already lowercased and stripped by `app.security.normalize_email`. Two
    # accounts differing only in case would be two accounts one person cannot tell
    # apart, so the uniqueness is over the normalized form -- which is the only form
    # that is ever written.
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    # What the header greets them by. Amazon's signup form asks for a name, this one
    # does too, and the header says "Hello, <name>" rather than showing an email
    # address on every page of a storefront someone might be browsing in public.
    name: Mapped[str] = mapped_column(String(120))
    # A bcrypt digest: algorithm, cost and salt are all inside the string, so rotating
    # the cost later needs no column change. 60 characters today; the column is wider
    # than that on purpose, because a future algorithm prefix should not need a schema
    # change in a project with no migrations.
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.id}>"


class Cart(Base):
    """One shopper's basket.

    A cart belongs either to a signed-in user or to an anonymous visitor identified by
    the opaque `session_token` in their cookie -- never to both, and never to neither.
    Both columns are nullable because exactly one of them is set at a time: Phase 12's
    `app.cart.merge_anonymous_cart` is what moves a cart from the second state to the
    first, setting `user_id` and clearing `session_token` in the same breath, so no cookie
    can still reach a cart an account now owns.

    Rows are created lazily, by the first add to cart. A visitor who only browses has no
    cart row and no cookie, so this table counts baskets rather than page views.
    """

    __tablename__ = "carts"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Deliberately a plain integer rather than a `ForeignKey("users.id")`, and not
    # unique, even though Phase 12 now writes it. There are no migrations here:
    # `create_all` cannot add a constraint to the `carts` table already in production, so
    # declaring one would make the models describe a schema the deployed database does
    # not have. `app.cart.merge_anonymous_cart` is the only function that sets this
    # column, and it is what keeps it pointing at a real user and at most one cart per
    # account -- an invariant held by the one write path rather than by a constraint only
    # fresh databases would get.
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # The signed value in the shopper's cookie is derived from this; the signature is
    # never stored, so a leaked database row cannot be replayed as a valid cookie.
    session_token: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    items: Mapped[list[CartItem]] = relationship(
        back_populates="cart",
        cascade="all, delete-orphan",
        # Stable order, so a line does not jump around the cart page between two
        # requests. Insertion order is also the order a shopper added things in, which
        # is the order they expect to read them back in.
        order_by="CartItem.id",
    )

    @property
    def item_count(self) -> int:
        """Total units in the cart -- what the header badge counts.

        Units, not lines: a shopper who added three of one thing has three items in
        their cart, which is what Amazon's badge says and what the subtotal line repeats.
        """
        return sum(item.quantity for item in self.items)

    @property
    def subtotal_cents(self) -> int:
        """The cart's total, in integer cents.

        Summed from the line totals, which are themselves integer arithmetic, so the
        number shown to a shopper is exact rather than nearly right. No float touches a
        price here or anywhere else in this file.
        """
        return sum(item.line_total_cents for item in self.items)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Cart {self.id}>"


class CartItem(Base):
    """One product in one cart, with how many of it the shopper wants."""

    __tablename__ = "cart_items"
    __table_args__ = (
        # One line per product per cart: adding a product already in the cart raises its
        # quantity. Two lines for the same product would show a shopper two prices for
        # one thing and leave "remove it" ambiguous, so the database refuses it outright
        # rather than trusting every write path to remember.
        UniqueConstraint("cart_id", "product_id", name="uq_cart_item_product"),
        # A line of zero is a line that should have been deleted, and a negative one
        # would subtract from the subtotal. Both are corrupt data, not edge cases.
        CheckConstraint("quantity >= 1", name="ck_cart_items_quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cart_id: Mapped[int] = mapped_column(ForeignKey("carts.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)

    cart: Mapped[Cart] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()

    @property
    def line_total_cents(self) -> int:
        """What this line costs: the unit price times the quantity, in integer cents.

        The multiplication happens here rather than in the template because it is money:
        the template's job is to format a number of cents, and its only arithmetic is the
        integer division that splits the dollars from the cents.
        """
        return self.product.price_cents * self.quantity

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CartItem cart={self.cart_id} product={self.product_id}>"
