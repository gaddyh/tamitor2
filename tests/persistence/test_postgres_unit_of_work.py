"""Postgres Unit of Work tests (requires Docker).

Receipt and idempotency changes share one transaction. If processing fails,
neither receipt nor operation claim may remain committed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from echo_v2.persistence.contacts import ContactRecord, PostgresContactRepository
from echo_v2.persistence.orm import UserRow
from echo_v2.persistence.user_resolver import PostgresUserResolver
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


async def test_postgres_contacts_upsert_and_scoped_case_insensitive_search(session_factory, clean_db):
    async with session_factory() as session:
        first = UserRow(phone_number="+972546610653", timezone="Asia/Jerusalem")
        second = UserRow(phone_number="+972546610654", timezone="UTC")
        session.add_all([first, second])
        await session.commit()
        first_id, second_id = str(first.id), str(second.id)

    repo = PostgresContactRepository(session_factory)
    phone = "+972501234567"
    original = ContactRecord(first_id, "Alice Smith", phone)
    another = ContactRecord(second_id, "Alice Other", phone)
    await repo.save(original)
    await repo.save(another)
    assert await repo.find_by_name(first_id, "  aLIce ") == original
    assert await repo.find_by_phone(first_id, phone) == original
    assert await repo.find_by_name(first_id, "Missing") is None
    assert await repo.find_by_phone(first_id, "+972500000000") is None
    assert await repo.find_by_name(second_id, "Smith") is None
    assert await repo.find_by_phone(second_id, phone) == another

    renamed = ContactRecord(first_id, "Alicia", phone)
    await repo.save(renamed)
    assert await repo.find_by_name(first_id, "Alice") is None
    assert await repo.find_by_phone(first_id, phone) == renamed
    assert await repo.find_by_phone(second_id, phone) == another
    async with session_factory() as session:
        count = (await session.execute(
            text("SELECT count(*) FROM contacts WHERE user_id = :uid"), {"uid": first_id}
        )).scalar_one()
    assert count == 1


async def test_postgres_user_resolver_normalization_timezone_fallback_and_missing(session_factory, clean_db):
    async with session_factory() as session:
        first = UserRow(phone_number="+972546610653", timezone="Asia/Jerusalem")
        second = UserRow(phone_number="+972546610654", timezone=None)
        session.add_all([first, second])
        await session.commit()
        first_id, second_id = str(first.id), str(second.id)

    async with session_factory() as session:
        resolver = PostgresUserResolver(session)
        assert await resolver.resolve("0546610653") == (first_id, "Asia/Jerusalem")
        assert await resolver.resolve("0546610654") == (second_id, "UTC")
        assert await resolver.resolve("+972546610655") is None
        assert await resolver.resolve("not-a-number") is None
