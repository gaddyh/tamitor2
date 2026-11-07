"""Fresh TamiTor foundation baseline (no legacy Echo schema).

Revision ID: 0001_tamitor_foundation
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001_tamitor_foundation"
down_revision = None
branch_labels = None
depends_on = None


def _id() -> sa.Column:
    return sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now())


def _updated_at() -> sa.Column:
    return sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    """Create business-number mappings, webhook receipts, and generic stores."""
    op.create_table("businesses",
        _id(),
        sa.Column("name", sa.Text(), nullable=False),
        _created_at(),
    )
    op.create_table("whatsapp_channels",
        _id(),
        sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_phone_number_id", sa.Text(), nullable=False),
        sa.Column("phone_number", sa.Text(), nullable=False),
        sa.Column("credentials", sa.LargeBinary(), nullable=True),
        _created_at(), _updated_at(),
        sa.UniqueConstraint("provider", "provider_phone_number_id", name="whatsapp_channels_provider_number_key"),
        sa.UniqueConstraint("id", "provider", name="whatsapp_channels_id_provider_key"),
    )
    op.create_index("ix_whatsapp_channels_business_id", "whatsapp_channels", ["business_id"])

    op.create_table("users",
        _id(),
        sa.Column("phone_number", sa.Text(), nullable=False, unique=True),
        sa.Column("timezone", sa.Text(), nullable=True),
        sa.Column("locale", sa.Text(), nullable=True),
        sa.Column("account_status", sa.Text(), nullable=False, server_default="active"),
        _created_at(), _updated_at(),
        sa.CheckConstraint("account_status IN ('active', 'suspended', 'deleted')", name="users_account_status_check"),
    )
    op.create_table("provider_webhook_events",
        sa.Column("provider", sa.Text(), primary_key=True),
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=True),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["channel_id", "provider"], ["whatsapp_channels.id", "whatsapp_channels.provider"],
            ondelete="CASCADE", name="provider_webhook_events_channel_provider_fkey",
        ),
    )
    op.create_index("ix_provider_webhook_events_channel_id", "provider_webhook_events", ["channel_id"])

    op.create_table("idempotency_operations",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("owner_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("outcome", JSONB(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        _created_at(), _updated_at(),
        sa.CheckConstraint("state IN ('IN_PROGRESS', 'SUCCESS', 'FAILURE', 'INDETERMINATE')", name="idempotency_operations_state_check"),
    )
    op.create_index("ix_idempotency_operations_state_lease", "idempotency_operations", ["state", "lease_expires_at"])

    op.create_table("contacts",
        _id(),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("phone_number", sa.Text(), nullable=False),
        _created_at(), _updated_at(),
        sa.UniqueConstraint("user_id", "phone_number", name="contacts_user_phone_key"),
    )
    op.create_index("ix_contacts_user_id", "contacts", ["user_id"])


def downgrade() -> None:
    """Reverse the fresh baseline (never invoked automatically)."""
    op.drop_index("ix_contacts_user_id", table_name="contacts")
    op.drop_table("contacts")
    op.drop_index("ix_idempotency_operations_state_lease", table_name="idempotency_operations")
    op.drop_table("idempotency_operations")
    op.drop_index("ix_provider_webhook_events_channel_id", table_name="provider_webhook_events")
    op.drop_table("provider_webhook_events")
    op.drop_table("users")
    op.drop_index("ix_whatsapp_channels_business_id", table_name="whatsapp_channels")
    op.drop_table("whatsapp_channels")
    op.drop_table("businesses")
