"""webhook_endpoints + webhook_deliveries

Revision ID: 005
Revises: 004
Create Date: 2026-05-26
"""

from alembic import op
import sqlalchemy as sa


revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_endpoints",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("secret", sa.String(), nullable=False),  # used to HMAC-sign deliveries
        sa.Column("description", sa.String(), nullable=True),
        # JSON array: ["approval.approved", "approval.rejected", ...] — empty = subscribe to all
        sa.Column("event_filter", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
    )

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("endpoint_id", sa.String(), sa.ForeignKey("webhook_endpoints.id"), nullable=False, index=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("event_type", sa.String(), nullable=False, index=True),
        sa.Column("action_id", sa.String(), nullable=True),  # the approval this came from, if any
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, default=0),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_snippet", sa.String(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), index=True),
    )


def downgrade() -> None:
    op.drop_table("webhook_deliveries")
    op.drop_table("webhook_endpoints")
