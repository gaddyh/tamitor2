"""Postgres-backed business webhook receipt tests (requires Docker)."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.asyncio


async def seed_channel(session_factory, provider: str = "360dialog", number_id: str = "123") -> str:
    """Insert a verified receiving number and return its channel ID."""
    async with session_factory() as session:
        business_id = (await session.execute(
            text("INSERT INTO businesses (name) VALUES ('Salon') RETURNING id")
        )).scalar_one()
        channel_id = (await session.execute(
            text("INSERT INTO whatsapp_channels (business_id, provider, provider_phone_number_id, phone_number) "
                 "VALUES (:bid, :provider, :number_id, '+972546610653') RETURNING id"),
            {"bid": business_id, "provider": provider, "number_id": number_id},
        )).scalar_one()
        await session.commit()
    return str(channel_id)


async def test_claim_first_returns_true(webhooks_repo, session_factory):
    channel_id = await seed_channel(session_factory)
    assert await webhooks_repo.claim("evt-1", provider="360dialog", channel_id=channel_id, event_type="message")


async def test_claim_duplicate_returns_false(webhooks_repo, session_factory):
    channel_id = await seed_channel(session_factory)
    assert await webhooks_repo.claim("evt-2", provider="360dialog", channel_id=channel_id)
    assert not await webhooks_repo.claim("evt-2", provider="360dialog", channel_id=channel_id)


async def test_claim_different_keys_both_succeed(webhooks_repo, session_factory):
    channel_id = await seed_channel(session_factory)
    assert await webhooks_repo.claim("evt-a", provider="360dialog", channel_id=channel_id)
    assert await webhooks_repo.claim("evt-b", provider="360dialog", channel_id=channel_id)


async def test_claim_same_event_other_provider(webhooks_repo, session_factory):
    first = await seed_channel(session_factory)
    second = await seed_channel(session_factory, provider="other", number_id="456")
    assert await webhooks_repo.claim("evt-shared", provider="360dialog", channel_id=first)
    assert await webhooks_repo.claim("evt-shared", provider="other", channel_id=second)


async def test_same_provider_number_cannot_belong_to_two_businesses(session_factory, clean_db):
    """Verified receiving number resolves to only one tenant."""
    await seed_channel(session_factory)
    async with session_factory() as session:
        business_id = (await session.execute(
            text("INSERT INTO businesses (name) VALUES ('Other Salon') RETURNING id")
        )).scalar_one()
        with pytest.raises(IntegrityError):
            await session.execute(
                text("INSERT INTO whatsapp_channels "
                     "(business_id, provider, provider_phone_number_id, phone_number) "
                     "VALUES (:bid, '360dialog', '123', '+972546610654')"),
                {"bid": business_id},
            )


async def test_receipt_rejects_channel_from_another_provider(webhooks_repo, session_factory):
    channel_id = await seed_channel(session_factory)
    with pytest.raises(IntegrityError):
        await webhooks_repo.claim("evt-wrong-provider", provider="other", channel_id=channel_id)


async def test_claim_requires_channel_id(webhooks_repo):
    with pytest.raises(ValueError, match="channel_id"):
        await webhooks_repo.claim("evt-x", provider="360dialog")


async def test_claim_requires_provider(webhooks_repo, session_factory):
    channel_id = await seed_channel(session_factory)
    with pytest.raises(ValueError, match="provider"):
        await webhooks_repo.claim("evt-y", channel_id=channel_id)


async def test_receipt_requires_verified_channel(webhooks_repo):
    with pytest.raises(IntegrityError):
        await webhooks_repo.claim("evt-unknown", provider="360dialog", channel_id="00000000-0000-0000-0000-000000000001")


async def test_schema_requires_channel_id(session_factory, clean_db):
    """A receipt without a verified channel cannot be inserted directly."""
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(text(
                "INSERT INTO provider_webhook_events (event_id, provider) VALUES ('evt-null', '360dialog')"
            ))
