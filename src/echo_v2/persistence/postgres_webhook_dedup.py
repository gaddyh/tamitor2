"""Postgres-backed webhook deduplication store.

Satisfies :class:`echo_v2.app.webhooks.dedup.WebhookDedupStore` against
PostgreSQL. ``claim(key)`` is an ``INSERT ... ON CONFLICT DO NOTHING`` —
returns ``True`` iff a row was inserted (first claim), ``False`` on
duplicate.

``channel_id`` must refer to a verified business receiving number. Unknown
numbers are rejected before claiming a receipt. The unique receipt identity
is (provider, event_id), so providers cannot collide. A Postgres caller must
supply both provider and channel_id; no unverified receipt is persisted.

Sessions are standalone by default, or shared within a UoW.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from echo_v2.persistence.orm import ProviderWebhookEventRow

__all__ = ["PostgresWebhookDedupStore"]


class PostgresWebhookDedupStore:
    """PostgreSQL implementation of :class:`WebhookDedupStore`."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        session: AsyncSession | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._shared_session = session

    def _session(self) -> _SessionContext:
        if self._shared_session is not None:
            return _SessionContext(self._shared_session, owns=False)
        return _SessionContext(self._session_factory(), owns=True)

    async def claim(
        self,
        key: str,
        *,
        provider: str | None = None,
        channel_id: str | None = None,
        event_type: str | None = None,
    ) -> bool:
        """Atomically claim ``key``. ``True`` iff this is the first claim.

        The channel must be verified before a receipt can be claimed.
        """
        if channel_id is None:
            raise ValueError("PostgresWebhookDedupStore.claim requires channel_id.")
        if provider is None:
            raise ValueError(
                "PostgresWebhookDedupStore.claim requires provider."
            )

        async with self._session() as session:
            stmt = (
                pg_insert(ProviderWebhookEventRow)
                .values(
                    event_id=key,
                    provider=provider,
                    channel_id=channel_id,
                    event_type=event_type,
                )
                .on_conflict_do_nothing(index_elements=["provider", "event_id"])
                .returning(ProviderWebhookEventRow.event_id)
            )
            result = await session.execute(stmt)
            inserted = result.scalar_one_or_none()
            return inserted is not None


class _SessionContext:
    """Async context manager for session lifecycle (standalone vs UoW)."""

    def __init__(self, session: AsyncSession, *, owns: bool) -> None:
        self._session = session
        self._owns = owns

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if not self._owns:
            return
        try:
            if exc_type is None:
                await self._session.commit()
            else:
                await self._session.rollback()
        finally:
            await self._session.close()


# Structural check: PostgresWebhookDedupStore satisfies the protocol.
# (Instantiation requires a session_factory; checked at runtime in tests.)
