"""360dialog webhook ingress route for TamiTor business numbers.

Static endpoint::

    POST /webhooks/bot/dialog360

Auth: when a provider/proxy is configured to send ``D360_WEBHOOK_SECRET``
in the ``Authorization`` header, validate it using a constant-time comparison.
Without that configuration the router alone does not authenticate requests.

Idempotency: the route deduplicates on ``event.event_id`` (the
WhatsApp message ID ``wamid.*``). 360dialog retries webhooks, so without
dedup the handler would process the same message multiple times.

The route does **only** ingress + auth + dedupe + dispatch to a handler.
Business resolution and conversation handling are separate responsibilities.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from echo_v2.app.webhooks.dedup import InMemoryWebhookDedupStore, WebhookDedupStore
from echo_v2.integrations.dialog360.events import Dialog360EventAdapter
from echo_v2.ports.bot import BotEventAdapter, BotEventHandler

__all__ = ["build_router"]

_logger = logging.getLogger("echo_v2.app.webhooks.dialog360")


def build_router(
    *,
    handler: BotEventHandler,
    webhook_secret: str,
    adapter: BotEventAdapter | None = None,
    dedup_store: WebhookDedupStore | None = None,
) -> APIRouter:
    """Build a 360dialog bot webhook router.

    Args:
        handler: The business-aware application handler that processes events.
        webhook_secret: The bearer secret expected in the Authorization header.
        adapter: Event adapter (defaults to :class:`Dialog360EventAdapter`).
        dedup_store: Webhook dedup store (defaults to in-memory).
    """
    router = APIRouter()
    parse_adapter = adapter or Dialog360EventAdapter()
    store = dedup_store or InMemoryWebhookDedupStore()
    has_secret = bool(webhook_secret)
    secret_hash = (
        hashlib.sha256(webhook_secret.encode("utf-8")).digest() if has_secret else b""
    )

    async def _handle_webhook(
        request: Request,
        authorization: str | None,
    ) -> dict[str, str]:
        try:
            payload = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid json") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="invalid payload")

        # Auth: bearer token (optional — if no secret configured, skip auth).
        # 360dialog does not send Authorization headers by default; the URL
        # itself acts as the shared secret. Set D360_WEBHOOK_SECRET to enforce
        # bearer auth if your 360dialog plan supports it.
        if has_secret and not _valid_bearer(authorization, secret_hash):
            raise HTTPException(status_code=401, detail="unauthorized")

        # Parse the webhook into a canonical BotEvent.
        event = parse_adapter.parse(payload)
        if event is None:
            return {"status": "ignored"}

        # Deduplicate on event_id (wamid).
        if not await store.claim(event.event_id):
            return {"status": "duplicate"}

        # Dispatch to the application handler.
        await handler.handle(event)
        return {"status": "received"}

    @router.post("/webhooks/bot/dialog360")
    async def dialog360_webhook(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        return await _handle_webhook(request, authorization)

    @router.post("/webhook/360dialog")
    async def dialog360_webhook_alt(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        return await _handle_webhook(request, authorization)

    return router


def _valid_bearer(authorization: str | None, expected_hash: bytes) -> bool:
    """Constant-time validation of a bearer token against the hash."""
    if not authorization:
        return False
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    candidate = parts[1].strip()
    candidate_hash = hashlib.sha256(candidate.encode("utf-8")).digest()
    return hmac.compare_digest(candidate_hash, expected_hash)
