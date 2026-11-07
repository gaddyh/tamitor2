"""Composition helpers for the Postgres persistence layer.

Builds standalone repositories and a :class:`PostgresUnitOfWork` factory
from :class:`DBSettings`. The engine is not connected until first use.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import async_sessionmaker

from echo_v2.persistence.contacts import PostgresContactRepository
from echo_v2.persistence.db import async_session_factory, create_async_engine_from_settings
from echo_v2.persistence.postgres_idempotency import PostgresIdempotencyStore
from echo_v2.persistence.postgres_webhook_dedup import PostgresWebhookDedupStore
from echo_v2.persistence.settings import DBSettings
from echo_v2.persistence.unit_of_work import PostgresUnitOfWork

__all__ = ["PostgresRepos", "build_postgres_repos"]


@dataclass
class PostgresRepos:
    """Standalone Postgres repositories + a UoW factory."""

    webhooks: PostgresWebhookDedupStore
    idempotency: PostgresIdempotencyStore
    contacts: PostgresContactRepository
    session_factory: async_sessionmaker
    unit_of_work: type[PostgresUnitOfWork]


def build_postgres_repos(settings: DBSettings) -> PostgresRepos:
    """Build generic Postgres repos + UoW factory from settings."""
    engine = create_async_engine_from_settings(settings)
    factory = async_session_factory(engine)

    webhooks = PostgresWebhookDedupStore(factory)
    idempotency = PostgresIdempotencyStore(factory)
    contacts = PostgresContactRepository(factory)

    # A UoW factory bound to the same session_factory.
    class _BoundUoW(PostgresUnitOfWork):
        def __init__(self) -> None:
            super().__init__(factory)

    return PostgresRepos(
        webhooks=webhooks,
        idempotency=idempotency,
        contacts=contacts,
        session_factory=factory,
        unit_of_work=_BoundUoW,
    )
