"""Unit tests for compose.py — generic Postgres wiring without a live DB."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from echo_v2.persistence.compose import PostgresRepos, build_postgres_repos
from echo_v2.persistence.contacts import (
    ContactRecord,
    ContactRepository,
    InMemoryContactRepository,
    PostgresContactRepository,
)
from echo_v2.persistence.postgres_idempotency import PostgresIdempotencyStore
from echo_v2.persistence.postgres_webhook_dedup import PostgresWebhookDedupStore
from echo_v2.persistence.settings import DBSettings
from echo_v2.persistence.unit_of_work import PostgresUnitOfWork
from echo_v2.persistence.user_resolver import (
    InMemoryUserResolver,
    PostgresUserResolver,
    UserResolver,
)


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


@pytest.mark.asyncio
async def test_contact_repository_interface_requires_implementations():
    repo = ContactRepository()
    contact = ContactRecord("user", "Ada", "+972546610653")
    with pytest.raises(NotImplementedError):
        await repo.save(contact)
    with pytest.raises(NotImplementedError):
        await repo.find_by_name("user", "Ada")
    with pytest.raises(NotImplementedError):
        await repo.find_by_phone("user", contact.phone_number)


@pytest.mark.asyncio
async def test_in_memory_contacts_upsert_and_scoped_lookups():
    repo = InMemoryContactRepository()
    original = ContactRecord("user-1", "  Alice Smith  ", "+972546610653")
    other_user = ContactRecord("user-2", "Alice Other", original.phone_number)
    await repo.save(original)
    await repo.save(other_user)

    assert await repo.find_by_name("user-1", "  aLIce ") == original
    assert await repo.find_by_phone("user-1", original.phone_number) == original
    assert await repo.find_by_name("user-1", "Nobody") is None
    assert await repo.find_by_name("user-3", "Alice") is None
    assert await repo.find_by_phone("user-3", original.phone_number) is None

    renamed = ContactRecord("user-1", "Alicia", original.phone_number)
    await repo.save(renamed)
    assert await repo.find_by_phone("user-1", original.phone_number) == renamed
    assert await repo.find_by_name("user-1", "Alice") is None
    assert await repo.find_by_phone("user-2", original.phone_number) == other_user


@pytest.mark.asyncio
async def test_in_memory_user_resolver_normalizes_and_handles_unknown_numbers():
    resolver = InMemoryUserResolver()
    assert isinstance(resolver, UserResolver)
    resolver.add_user("0546610653", "user-1")
    resolver.add_user("+14155552671", "user-2", "America/Los_Angeles")
    assert await resolver.resolve("+972546610653") == ("user-1", "Asia/Jerusalem")
    assert await resolver.resolve("415-555-2671") is None
    assert await resolver.resolve("+14155552671") == ("user-2", "America/Los_Angeles")
    assert await resolver.resolve("+972546610654") is None
    assert await resolver.resolve("invalid") is None


@pytest.mark.asyncio
async def test_postgres_user_resolver_with_session_result():
    result = SimpleNamespace(first=lambda: SimpleNamespace(id="user-1", timezone=None))
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    resolver = PostgresUserResolver(session)
    assert await resolver.resolve("0546610653") == ("user-1", "UTC")
    stmt = session.execute.await_args.args[0]
    assert "users.phone_number" in str(stmt)
    assert "+972546610653" in stmt.compile().params.values()

    session.execute.return_value = SimpleNamespace(first=lambda: None)
    assert await resolver.resolve("+972546610654") is None
    before = session.execute.await_count
    assert await resolver.resolve("invalid") is None
    assert session.execute.await_count == before
