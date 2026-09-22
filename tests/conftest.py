import os
import tempfile

# Point the app at a throwaway SQLite file before anything reads the settings, so a test
# run never touches (or creates) the developer's local database.
_TEST_DB = os.path.join(tempfile.mkdtemp(prefix="amazonia-test-"), "test.db")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import create_schema, get_db, get_sessionmaker  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from seed.seed import load_catalog, seed  # noqa: E402


@pytest.fixture(scope="session")
def catalog() -> dict:
    """The committed catalog file -- the same data production serves."""
    return load_catalog()


@pytest.fixture(scope="session", autouse=True)
def seeded_database(catalog) -> None:
    """Seed the throwaway database once, with the real catalog.

    The page tests assert on real seeded titles and prices rather than on fixtures
    invented for the test, so "the landing page renders the catalog" is checked against
    the catalog that actually ships.
    """
    create_schema()
    session = get_sessionmaker()()
    try:
        seed(session, catalog)
        session.commit()
    finally:
        session.close()


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def empty_client(tmp_path) -> TestClient:
    """A client whose database has the schema but no rows, for the empty states.

    Overriding the `get_db` dependency is what makes this possible without a second
    process: the app is unchanged, only the session it is handed for these requests.
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    Base.metadata.create_all(engine)
    empty_sessionmaker = sessionmaker(bind=engine, expire_on_commit=False)

    def empty_db():
        session = empty_sessionmaker()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = empty_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
