"""Postgres-backed idempotency store tests (requires Docker).

Covers the lease + fencing-token concurrency model from the plan:
* reserve() ACQUIRED / IN_PROGRESS / COMPLETED
* concurrent reservation (only one ACQUIRED)
* expired lease reclaim inside reserve()
* token-guarded terminal writes (fencing against stale owner)
* release + renew_lease
* wait_for_completion polling
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from echo_v2.persistence import postgres_idempotency
from echo_v2.persistence.postgres_idempotency import PostgresIdempotencyStore
from echo_v2.runtime.errors import RetryableError
from echo_v2.runtime.idempotency import (
    IndeterminateOutcome,
    LostOwnershipError,
    PermanentFailureOutcome,
    ReserveStatus,
    SuccessOutcome,
)

pytestmark = pytest.mark.asyncio


async def test_reserve_acquired_then_in_progress(idempotency_repo):
    r1 = await idempotency_repo.reserve("k1")
    assert r1.status == ReserveStatus.ACQUIRED
    assert r1.owner_token is not None

    r2 = await idempotency_repo.reserve("k1")
    assert r2.status == ReserveStatus.IN_PROGRESS
    assert r2.owner_token is None


async def test_reserve_completed_after_success(idempotency_repo):
    r = await idempotency_repo.reserve("k2")
    await idempotency_repo.put_success(
        "k2", r.owner_token, SuccessOutcome(value=42, attempts=1, duration_ms=1.0)
    )
    r2 = await idempotency_repo.reserve("k2")
    assert r2.status == ReserveStatus.COMPLETED


async def test_get_returns_none_for_unknown(idempotency_repo):
    assert await idempotency_repo.get("missing") is None


async def test_get_returns_none_for_in_progress(idempotency_repo):
    await idempotency_repo.reserve("k3")
    assert await idempotency_repo.get("k3") is None


async def test_put_success_round_trip(idempotency_repo):
    r = await idempotency_repo.reserve("k4")
    await idempotency_repo.put_success(
        "k4", r.owner_token, SuccessOutcome(value="hello", attempts=2, duration_ms=5.5)
    )
    outcome = await idempotency_repo.get("k4")
    assert isinstance(outcome, SuccessOutcome)
    assert outcome.value == "hello"
    assert outcome.attempts == 2
    assert outcome.duration_ms == 5.5


async def test_put_failure_round_trip(idempotency_repo):
    r = await idempotency_repo.reserve("k5")
    await idempotency_repo.put_failure(
        "k5", r.owner_token, PermanentFailureOutcome(error_type="ValueError", error_message="bad")
    )
    outcome = await idempotency_repo.get("k5")
    assert isinstance(outcome, PermanentFailureOutcome)
    assert outcome.error_type == "ValueError"
    assert outcome.error_message == "bad"


async def test_put_indeterminate_round_trip(idempotency_repo):
    r = await idempotency_repo.reserve("k6")
    await idempotency_repo.put_indeterminate(
        "k6", r.owner_token, IndeterminateOutcome(error_type="TimeoutError", error_message="timed out")
    )
    outcome = await idempotency_repo.get("k6")
    assert isinstance(outcome, IndeterminateOutcome)
    assert outcome.error_type == "TimeoutError"


async def test_wrong_token_terminal_write_raises_lost_ownership(idempotency_repo):
    """Fencing: a stale owner cannot overwrite after a new owner reclaimed."""
    r1 = await idempotency_repo.reserve("k7")
    # Simulate lease expiry by backdating the row.
    from sqlalchemy import text as sql_text

    async with idempotency_repo._session_factory() as session:  # type: ignore[attr-defined]
        await session.execute(
            sql_text(
                "UPDATE idempotency_operations SET lease_expires_at = now() - interval '1 hour' "
                "WHERE key = 'k7'"
            )
        )
        await session.commit()

    # A new caller reclaims.
    r2 = await idempotency_repo.reserve("k7")
    assert r2.status == ReserveStatus.ACQUIRED
    assert r2.owner_token != r1.owner_token

    # The stale owner (r1) tries to write — must fail.
    with pytest.raises(LostOwnershipError):
        await idempotency_repo.put_success(
            "k7", r1.owner_token, SuccessOutcome(value=1, attempts=1, duration_ms=1.0)
        )

    # The new owner (r2) writes successfully.
    await idempotency_repo.put_success(
        "k7", r2.owner_token, SuccessOutcome(value=2, attempts=1, duration_ms=1.0)
    )
    outcome = await idempotency_repo.get("k7")
    assert isinstance(outcome, SuccessOutcome)
    assert outcome.value == 2  # new owner's value, not stale


async def test_expired_lease_reclaimed_in_reserve(idempotency_repo, session_factory):
    """reserve() atomically reclaims an expired lease — crash recovery."""
    r1 = await idempotency_repo.reserve("k8")
    # Backdate the lease.
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE idempotency_operations SET lease_expires_at = now() - interval '1 hour' "
                "WHERE key = 'k8'"
            )
        )
        await session.commit()

    r2 = await idempotency_repo.reserve("k8")
    assert r2.status == ReserveStatus.ACQUIRED
    assert r2.owner_token is not None
    assert r2.owner_token != r1.owner_token


async def test_release_deletes_in_progress_row(idempotency_repo):
    r = await idempotency_repo.reserve("k9")
    await idempotency_repo.release("k9", r.owner_token)
    # After release, reserve can re-acquire.
    r2 = await idempotency_repo.reserve("k9")
    assert r2.status == ReserveStatus.ACQUIRED


async def test_release_wrong_token_raises_lost_ownership(idempotency_repo):
    await idempotency_repo.reserve("k10")
    wrong = uuid.uuid4()
    with pytest.raises(LostOwnershipError):
        await idempotency_repo.release("k10", wrong)


async def test_renew_lease_extends_expiry(idempotency_repo):
    r = await idempotency_repo.reserve("k11")
    assert await idempotency_repo.renew_lease("k11", r.owner_token) is True


async def test_renew_lease_wrong_token_returns_false(idempotency_repo):
    await idempotency_repo.reserve("k12")
    wrong = uuid.uuid4()
    assert await idempotency_repo.renew_lease("k12", wrong) is False


async def test_renew_lease_after_terminal_returns_false(idempotency_repo):
    r = await idempotency_repo.reserve("k13")
    await idempotency_repo.put_success(
        "k13", r.owner_token, SuccessOutcome(value=1, attempts=1, duration_ms=1.0)
    )
    assert await idempotency_repo.renew_lease("k13", r.owner_token) is False


async def test_concurrent_reserve_only_one_acquired(session_factory, clean_db):
    """Two independent sessions racing on the same key — only one ACQUIRED."""
    store_a = PostgresIdempotencyStore(session_factory, lease_seconds=10)
    store_b = PostgresIdempotencyStore(session_factory, lease_seconds=10)

    r_a, r_b = await asyncio.gather(
        store_a.reserve("k14"),
        store_b.reserve("k14"),
    )
    acquired = [r for r in (r_a, r_b) if r.status == ReserveStatus.ACQUIRED]
    in_progress = [r for r in (r_a, r_b) if r.status == ReserveStatus.IN_PROGRESS]
    assert len(acquired) == 1
    assert len(in_progress) == 1


async def test_wait_for_completion_returns_outcome(idempotency_repo):
    r = await idempotency_repo.reserve("k15")
    await idempotency_repo.put_success(
        "k15", r.owner_token, SuccessOutcome(value=99, attempts=1, duration_ms=1.0)
    )
    outcome = await idempotency_repo.wait_for_completion("k15")
    assert isinstance(outcome, SuccessOutcome)
    assert outcome.value == 99


async def test_wait_for_completion_polls_until_done(idempotency_repo):
    """A waiter polls and eventually sees the owner's terminal outcome."""
    r = await idempotency_repo.reserve("k16")

    async def owner():
        await asyncio.sleep(0.1)
        await idempotency_repo.put_success(
            "k16", r.owner_token, SuccessOutcome(value=7, attempts=1, duration_ms=1.0)
        )

    async def waiter():
        return await idempotency_repo.wait_for_completion("k16")

    owner_task = asyncio.create_task(owner())
    outcome = await asyncio.wait_for(waiter(), timeout=5.0)
    assert isinstance(outcome, SuccessOutcome)
    assert outcome.value == 7
    await owner_task


async def test_wait_for_completion_released_raises_retryable(idempotency_repo):
    r = await idempotency_repo.reserve("k17")
    await idempotency_repo.release("k17", r.owner_token)
    with pytest.raises(RetryableError):
        await idempotency_repo.wait_for_completion("k17")


@pytest.mark.parametrize("next_state, expected_status", [
    ("IN_PROGRESS", ReserveStatus.IN_PROGRESS),
    ("SUCCESS", ReserveStatus.COMPLETED),
])
async def test_reserve_losing_reclaim_race_rereads_state(
    idempotency_repo, session_factory, monkeypatch, next_state, expected_status
):
    await idempotency_repo.reserve("reclaim-race")
    async with session_factory() as session:
        await session.execute(text(
            "UPDATE idempotency_operations SET lease_expires_at = now() - interval '1 hour' "
            "WHERE key = 'reclaim-race'"
        ))
        await session.commit()

    original_fetch = postgres_idempotency._fetch_row
    calls = 0

    async def fetch_after_race(session, key):
        nonlocal calls
        calls += 1
        row = await original_fetch(session, key)
        if calls == 2:
            return SimpleNamespace(state=next_state)
        return row

    monkeypatch.setattr(postgres_idempotency, "_fetch_row", fetch_after_race)
    monkeypatch.setattr(postgres_idempotency, "_try_reclaim", AsyncMock(return_value=False))
    result = await idempotency_repo.reserve("reclaim-race")
    assert result.status is expected_status
    assert result.owner_token is None
    assert calls == 2


async def test_get_terminal_row_without_outcome_returns_none(idempotency_repo, session_factory):
    claim = await idempotency_repo.reserve("empty-outcome")
    async with session_factory() as session:
        await session.execute(text(
            "UPDATE idempotency_operations SET state = 'SUCCESS', owner_token = NULL, "
            "lease_expires_at = NULL WHERE key = 'empty-outcome'"
        ))
        await session.commit()
    assert claim.status is ReserveStatus.ACQUIRED
    assert await idempotency_repo.get("empty-outcome") is None


async def test_wait_for_completion_reads_outcome_after_completed_reservation(idempotency_repo, monkeypatch):
    outcome = SuccessOutcome(value=8, attempts=1, duration_ms=1.0)
    get = AsyncMock(side_effect=[None, outcome])
    reserve = AsyncMock(return_value=postgres_idempotency.ReserveResult(ReserveStatus.COMPLETED))
    monkeypatch.setattr(idempotency_repo, "get", get)
    monkeypatch.setattr(idempotency_repo, "reserve", reserve)
    assert await idempotency_repo.wait_for_completion("completed-race") == outcome
    assert get.await_count == 2


async def test_wait_for_completion_completed_without_outcome_is_retryable(idempotency_repo, monkeypatch):
    monkeypatch.setattr(idempotency_repo, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(idempotency_repo, "reserve", AsyncMock(
        return_value=postgres_idempotency.ReserveResult(ReserveStatus.COMPLETED)
    ))
    with pytest.raises(RetryableError, match="did not complete"):
        await idempotency_repo.wait_for_completion("missing-outcome")


async def test_wait_for_completion_times_out(idempotency_repo, monkeypatch):
    monkeypatch.setattr(postgres_idempotency, "_POLL_TIMEOUT_SECONDS", 0)
    with pytest.raises(RetryableError, match="Timed out waiting"):
        await idempotency_repo.wait_for_completion("never-completes")
