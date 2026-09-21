"""Phase 2: the app is deployable -- container, blueprint, and a Postgres-ready engine.

These tests guard the parts of the deploy that are easy to break silently and expensive
to discover in production: the driver in the database URL, the health check path Render
polls, and the promise that no secret is committed.
"""

from pathlib import Path

import pytest

from app.config import (
    DEV_DATABASE_URL,
    DEV_SECRET_KEY,
    Settings,
    get_settings,
    normalize_database_url,
)
from app.db import make_engine

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "given",
    ["postgres://u:p@host:5432/db", "postgresql://u:p@host:5432/db"],
)
def test_postgres_urls_get_an_explicit_psycopg_driver(given):
    """Bare Postgres URLs would send SQLAlchemy looking for psycopg2, which is absent."""
    assert normalize_database_url(given) == "postgresql+psycopg://u:p@host:5432/db"


def test_sqlite_url_is_left_alone():
    assert normalize_database_url(DEV_DATABASE_URL) == DEV_DATABASE_URL


def test_an_already_qualified_url_is_not_mangled():
    qualified = "postgresql+psycopg://u:p@host/db"
    assert normalize_database_url(qualified) == qualified


def test_engine_for_postgres_uses_psycopg():
    """Built without connecting: this checks the wiring, not a live server."""
    engine = make_engine(normalize_database_url("postgresql://u:p@host:5432/db"))
    assert engine.dialect.name == "postgresql"
    assert engine.dialect.driver == "psycopg"


def test_engine_for_sqlite_allows_cross_thread_use():
    engine = make_engine(DEV_DATABASE_URL)
    assert engine.dialect.name == "sqlite"
    assert engine.pool._dialect  # engine is usable
    assert engine.url.database == "./app.db"


def test_production_is_detected_from_the_supplied_secret():
    dev = Settings(DEV_DATABASE_URL, DEV_SECRET_KEY, 8000, "amazonia", False)
    deployed = Settings(
        "postgresql+psycopg://u:p@h/db", "a-real-generated-secret", 10000, "amazonia", True
    )
    assert not dev.is_production
    assert deployed.is_production


def test_a_supplied_database_url_is_recorded_as_coming_from_the_environment(monkeypatch):
    """The startup log has to distinguish a missing URL from one that names SQLite."""
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host:5432/db")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.database_url_from_env
    assert settings.database_url == "postgresql+psycopg://u:p@host:5432/db"
    get_settings.cache_clear()


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_database_url_falls_back_to_the_local_default(monkeypatch, blank):
    """A platform env var created but left empty must not produce an unusable URL."""
    monkeypatch.setenv("DATABASE_URL", blank)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.database_url == DEV_DATABASE_URL
    assert not settings.database_url_from_env
    get_settings.cache_clear()


def test_healthz_is_what_the_blueprint_polls():
    """A health check pointed at a path that does not exist fails every deploy."""
    blueprint = (REPO_ROOT / "render.yaml").read_text()
    assert "healthCheckPath: /healthz" in blueprint


def test_blueprint_takes_the_database_url_from_the_managed_database():
    blueprint = (REPO_ROOT / "render.yaml").read_text()
    assert "fromDatabase:" in blueprint
    assert "generateValue: true" in blueprint  # SECRET_KEY, not a committed literal


def test_no_secret_is_committed_in_the_blueprint_or_container():
    for name in ("render.yaml", "Dockerfile"):
        text = (REPO_ROOT / name).read_text()
        assert DEV_SECRET_KEY not in text
        assert "SECRET_KEY=" not in text


def test_the_container_binds_to_the_platform_port():
    """Render routes to $PORT; a hardcoded port means the service never passes health."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    assert "${PORT:-8000}" in dockerfile
    assert "--host 0.0.0.0" in dockerfile


def test_the_build_context_excludes_local_state_and_reference_material():
    ignored = (REPO_ROOT / ".dockerignore").read_text().split()
    for entry in (".venv/", "app.db", "amazon_screenshots/", ".git"):
        assert entry in ignored
