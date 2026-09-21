import os
import tempfile

# Point the app at a throwaway SQLite file before anything reads the settings, so a test
# run never touches (or creates) the developer's local database.
_TEST_DB = os.path.join(tempfile.mkdtemp(prefix="amazonia-test-"), "test.db")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client
