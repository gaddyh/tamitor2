"""SQLAlchemy ORM models for the TamiTor foundation database.

The baseline migration is the production schema source of truth. Keep these
models aligned with it for repository mapping and test convenience.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TIMESTAMP, LargeBinary, Uuid

__all__ = [
    "Base",
    "BusinessRow",
    "WhatsAppChannelRow",
    "ContactRow",
    "IdempotencyOperationRow",
    "ProviderWebhookEventRow",
    "UserRow",
]


class Base(DeclarativeBase):
    """Declarative base for TamiTor ORM models."""


# --- businesses and verified receiving numbers ----------------------------


class BusinessRow(Base):
    """Tenant owning a WhatsApp Business number."""

    __tablename__ = "businesses"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class WhatsAppChannelRow(Base):
    """Verified provider phone-number ID mapping to exactly one business.

    Credentials are encrypted before storage using CredentialCipher; they may
    be absent for integrations that use a shared provider credential.
    """

    __tablename__ = "whatsapp_channels"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    business_id: Mapped[str] = mapped_column(Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_phone_number_id: Mapped[str] = mapped_column(Text, nullable=False)
    phone_number: Mapped[str] = mapped_column(Text, nullable=False)
    credentials: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("provider", "provider_phone_number_id", name="whatsapp_channels_provider_number_key"),
        UniqueConstraint("id", "provider", name="whatsapp_channels_id_provider_key"),
        Index("ix_whatsapp_channels_business_id", "business_id"),
    )


# --- users -----------------------------------------------------------------


class UserRow(Base):
    """Optional phone identity anchor retained for the generic user resolver."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    phone_number: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    timezone: Mapped[str | None] = mapped_column(Text, nullable=True)
    locale: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("account_status IN ('active', 'suspended', 'deleted')", name="users_account_status_check"),
    )


# --- provider webhook receipts ---------------------------------------------


class ProviderWebhookEventRow(Base):
    """Durable receipt metadata, never a raw provider payload.

    A verified channel is required before claiming an event. Provider and
    event ID together identify a delivery, preventing cross-provider collisions.
    """

    __tablename__ = "provider_webhook_events"

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    channel_id: Mapped[str] = mapped_column(Uuid, nullable=False)
    event_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["channel_id", "provider"], ["whatsapp_channels.id", "whatsapp_channels.provider"],
            ondelete="CASCADE", name="provider_webhook_events_channel_provider_fkey",
        ),
        Index("ix_provider_webhook_events_channel_id", "channel_id"),
    )


# --- idempotency operations ------------------------------------------------


class IdempotencyOperationRow(Base):
    """Persistent idempotency record with lease + fencing-token semantics."""

    __tablename__ = "idempotency_operations"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    owner_token: Mapped[str | None] = mapped_column(Uuid, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    outcome: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    attempts: Mapped[int | None] = mapped_column(nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(nullable=True)
    error_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("state IN ('IN_PROGRESS', 'SUCCESS', 'FAILURE', 'INDETERMINATE')", name="idempotency_operations_state_check"),
        Index("ix_idempotency_operations_state_lease", "state", "lease_expires_at"),
    )


# --- contacts --------------------------------------------------------------


class ContactRow(Base):
    """Optional saved phone contact for a user."""

    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[str] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    phone_number: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "phone_number", name="contacts_user_phone_key"),
        Index("ix_contacts_user_id", "user_id"),
    )
