"""Unit of Work: one AsyncSession/transaction shared across generic stores.

Webhook receipts and idempotency writes can share a transaction. Repositories
in UoW mode do not commit individually; the UoW commits on clean exit or
rolls back on exception. Standalone methods use their own short sessions.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from echo_v2.persistence.postgres_idempotency import PostgresIdempotencyStore
from echo_v2.persistence.postgres_webhook_dedup import PostgresWebhookDedupStore

__all__ = ["PostgresUnitOfWork", "UnitOfWorkRepos"]


@dataclass
class UnitOfWorkRepos:
    """Stores bound to a single shared session."""

    webhooks: PostgresWebhookDedupStore
    idempotency: PostgresIdempotencyStore


class PostgresUnitOfWork:
    """One AsyncSession + one transaction, shared across stores."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        lease_seconds: int = 30,
    ) -> None:
        self._session_factory = session_factory
        self._lease_seconds = lease_seconds
        self._session: AsyncSession | None = None
        self.repos: UnitOfWorkRepos | None = None

    async def __aenter__(self) -> PostgresUnitOfWork:  # noqa: PYI034
        self._session = self._session_factory()
        self.repos = UnitOfWorkRepos(
            webhooks=PostgresWebhookDedupStore(self._session_factory, session=self._session),
            idempotency=PostgresIdempotencyStore(
                self._session_factory,
                session=self._session,
                lease_seconds=self._lease_seconds,
            ),
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        assert self._session is not None
        try:
            if exc_type is None:
                await self._session.commit()
            else:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None
            self.repos = None

    @property
    def webhooks(self) -> PostgresWebhookDedupStore:
        assert self.repos is not None, "UnitOfWork not entered"
        return self.repos.webhooks

    @property
    def idempotency(self) -> PostgresIdempotencyStore:
        assert self.repos is not None, "UnitOfWork not entered"
        return self.repos.idempotency
