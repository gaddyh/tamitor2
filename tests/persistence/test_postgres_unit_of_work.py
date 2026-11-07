"""Postgres Unit of Work tests (requires Docker).

Receipt and idempotency changes share one transaction. If processing fails,
neither receipt nor operation claim may remain committed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from echo_v2.runtime.idempotency import ReserveStatus
from tests.persistence.test_postgres_webhook_dedup import seed_channel

pytestmark = pytest.mark.asyncio


async def test_uow_claims_receipt_and_operation_atomically(unit_of_work_factory, session_factory):
    """The happy path: both writes commit together."""
    channel_id = await seed_channel(session_factory)
    async with unit_of_work_factory() as uow:
        assert await uow.webhooks.claim("evt-uow-1", provider="360dialog", channel_id=channel_id)
        result = await uow.idempotency.reserve("op-uow-1")
        assert result.status is ReserveStatus.ACQUIRED

    # Both committed.
    async with session_factory() as session:
        assert (await session.execute(text(
            "SELECT event_id FROM provider_webhook_events WHERE event_id='evt-uow-1'"
        ))).scalar_one() == "evt-uow-1"
        assert (await session.execute(text(
            "SELECT key FROM idempotency_operations WHERE key='op-uow-1'"
        ))).scalar_one() == "op-uow-1"


async def test_uow_rollback_on_exception(unit_of_work_factory, session_factory):
    """An exception after both claims rolls both back."""
    channel_id = await seed_channel(session_factory)
    with pytest.raises(RuntimeError):
        async with unit_of_work_factory() as uow:
            assert await uow.webhooks.claim("evt-uow-2", provider="360dialog", channel_id=channel_id)
            assert (await uow.idempotency.reserve("op-uow-2")).status is ReserveStatus.ACQUIRED
            raise RuntimeError("simulated processing failure")

    # The claim was rolled back — the event row must not exist.
    async with session_factory() as session:
        assert (await session.execute(text(
            "SELECT event_id FROM provider_webhook_events WHERE event_id='evt-uow-2'"
        ))).scalar_one_or_none() is None
        assert (await session.execute(text(
            "SELECT key FROM idempotency_operations WHERE key='op-uow-2'"
        ))).scalar_one_or_none() is None


async def test_uow_repos_share_one_session(unit_of_work_factory):
    """Both stores in a UoW use the same AsyncSession (no independent commits)."""
    async with unit_of_work_factory() as uow:
        # The shared session is the same object across repos.
        assert uow.webhooks._shared_session is uow.idempotency._shared_session


async def test_uow_claim_duplicate_inside_transaction(unit_of_work_factory, session_factory):
    """A second claim for the same event inside a UoW returns False (duplicate)."""
    channel_id = await seed_channel(session_factory)
    async with unit_of_work_factory() as uow:
        first = await uow.webhooks.claim("evt-uow-3", provider="360dialog", channel_id=channel_id)
        second = await uow.webhooks.claim("evt-uow-3", provider="360dialog", channel_id=channel_id)
        assert first is True
        assert second is False
