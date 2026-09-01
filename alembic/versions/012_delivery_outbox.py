"""transactional delivery outbox

Revision ID: 012
Revises: 011
Create Date: 2026-08-31
"""

import sqlalchemy as sa

from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivery_outbox",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("action_id", sa.String(), sa.ForeignKey("approvals.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column(
            "notification_attempt_id",
            sa.String(),
            sa.ForeignKey("notification_attempts.id"),
            nullable=True,
            unique=True,
        ),
        sa.Column(
            "webhook_delivery_id",
            sa.String(),
            sa.ForeignKey("webhook_deliveries.id"),
            nullable=True,
            unique=True,
        ),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("lease_owner", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "dedupe_key",
            name="uq_delivery_outbox_tenant_dedupe",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'delivered', 'dead', 'canceled')",
            name="ck_delivery_outbox_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_delivery_outbox_attempt_count",
        ),
        sa.CheckConstraint(
            "(kind IN ('approval.email', 'approval.sms') "
            "AND notification_attempt_id IS NOT NULL AND webhook_delivery_id IS NULL) OR "
            "(kind = 'approval.webhook' "
            "AND notification_attempt_id IS NULL AND webhook_delivery_id IS NOT NULL)",
            name="ck_delivery_outbox_kind_target",
        ),
    )
    op.create_index(
        "ix_delivery_outbox_tenant_id",
        "delivery_outbox",
        ["tenant_id"],
    )
    op.create_index(
        "ix_delivery_outbox_action_id",
        "delivery_outbox",
        ["action_id"],
    )
    op.create_index(
        "ix_delivery_outbox_ready",
        "delivery_outbox",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "ix_delivery_outbox_stale",
        "delivery_outbox",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_delivery_outbox_stale", table_name="delivery_outbox")
    op.drop_index("ix_delivery_outbox_ready", table_name="delivery_outbox")
    op.drop_index("ix_delivery_outbox_action_id", table_name="delivery_outbox")
    op.drop_index("ix_delivery_outbox_tenant_id", table_name="delivery_outbox")
    op.drop_table("delivery_outbox")
