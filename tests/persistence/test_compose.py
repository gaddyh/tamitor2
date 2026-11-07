"""Unit tests for compose.py — generic Postgres wiring without a live DB."""

from __future__ import annotations

from echo_v2.persistence.compose import PostgresRepos, build_postgres_repos
from echo_v2.persistence.contacts import PostgresContactRepository
from echo_v2.persistence.postgres_idempotency import PostgresIdempotencyStore
from echo_v2.persistence.postgres_webhook_dedup import PostgresWebhookDedupStore
from echo_v2.persistence.settings import DBSettings
from echo_v2.persistence.unit_of_work import PostgresUnitOfWork


def _settings() -> DBSettings:
    return DBSettings(
        database_url="postgresql+psycopg://u:p@localhost:5432/db",
        credential_key=None,
        default_phone_region="IL",
        pool_size=5,
        echo=False,
    )


def test_build_postgres_repos_returns_postgres_repos():
    repos = build_postgres_repos(_settings())
    assert isinstance(repos, PostgresRepos)


def test_build_postgres_repos_builds_generic_repos():
    repos = build_postgres_repos(_settings())
    assert isinstance(repos.webhooks, PostgresWebhookDedupStore)
    assert isinstance(repos.idempotency, PostgresIdempotencyStore)
    assert isinstance(repos.contacts, PostgresContactRepository)


def test_build_postgres_repos_session_factory_is_set():
    repos = build_postgres_repos(_settings())
    assert repos.session_factory is not None


def test_build_postgres_repos_uow_factory_is_subclass():
    repos = build_postgres_repos(_settings())
    assert issubclass(repos.unit_of_work, PostgresUnitOfWork)


def test_build_postgres_repos_uow_factory_constructs():
    repos = build_postgres_repos(_settings())
    uow = repos.unit_of_work()
    assert isinstance(uow, PostgresUnitOfWork)
    assert uow._session_factory is repos.session_factory


def test_build_postgres_repos_repos_share_session_factory():
    repos = build_postgres_repos(_settings())
    # All stores should share the same session factory.
    assert repos.contacts._session_factory is repos.webhooks._session_factory
    assert repos.webhooks._session_factory is repos.idempotency._session_factory
