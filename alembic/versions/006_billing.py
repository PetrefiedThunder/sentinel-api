"""tenants.plan + stripe_customer_id + stripe_subscription_id

Revision ID: 006
Revises: 005
Create Date: 2026-05-26
"""

from alembic import op
import sqlalchemy as sa


revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Default everyone to 'free' — explicit upgrade flips to 'pro' or 'enterprise'
    op.add_column(
        "tenants",
        sa.Column("plan", sa.String(), nullable=False, server_default="free"),
    )
    op.add_column(
        "tenants",
        sa.Column("stripe_customer_id", sa.String(), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("stripe_subscription_id", sa.String(), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("plan_updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_tenants_stripe_customer_id",
        "tenants",
        ["stripe_customer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_tenants_stripe_customer_id", table_name="tenants")
    op.drop_column("tenants", "plan_updated_at")
    op.drop_column("tenants", "stripe_subscription_id")
    op.drop_column("tenants", "stripe_customer_id")
    op.drop_column("tenants", "plan")
