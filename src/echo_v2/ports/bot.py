"""Provider-neutral WhatsApp message transport types for TamiTor.

The business number is resolved separately from the customer's phone so that
messages cannot cross tenant boundaries. Provider-specific credentials stay
inside the transport implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable

__all__ = [
    "BotChannel",
    "BotContact",
    "BotEvent",
    "BotEventAdapter",
    "BotEventHandler",
    "BotEventType",
]


class BotEventType(Enum):
    """Type of incoming bot event."""

    TEXT = "text"
    CONTACT = "contact"


@dataclass(frozen=True)
class BotContact:
    """A shared contact (vCard) extracted from a bot message.

    ``phone`` is the shared contact's phone number in E.164 or raw form.
    ``name`` is the display name for confirmation messages.
    """

    phone: str
    name: str


@dataclass(frozen=True)
class BotEvent:
    """An incoming event from a business's WhatsApp number.

    ``user_phone`` is the customer's number; ``business_phone_number_id``
    identifies the receiving business channel when present in the webhook.
    """

    event_id: str
    user_phone: str
    type: BotEventType
    text: str | None = None
    contact: BotContact | None = None
    timestamp: datetime | None = None
    business_phone_number_id: str | None = None


@runtime_checkable
class BotEventAdapter(Protocol):
    """Parse a raw provider webhook payload into a :class:`BotEvent`.

    Pure and synchronous: no I/O, no user lookup. Returns ``None`` for
    payloads the adapter deliberately ignores (status updates, non-message
    webhooks, unknown types). Never raises on unknown shapes — returns
    ``None`` so an unexpected payload never breaks the webhook ingress.
    """

    def parse(self, payload: dict) -> BotEvent | None: ...


@runtime_checkable
class BotEventHandler(Protocol):
    """Process an authenticated incoming message after tenant resolution."""

    async def handle(self, event: BotEvent) -> None: ...


@runtime_checkable
class BotChannel(Protocol):
    """Send a message via a business's configured WhatsApp channel."""

    async def send_text(self, user_phone: str, text: str) -> None: ...
