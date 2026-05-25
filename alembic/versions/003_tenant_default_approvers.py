"""tenants.default_approvers

Revision ID: 003_tenant_default_approvers
Revises: 002_contacts_notifications
Create Date: 2026-05-25
"""

from alembic import op
import sqlalchemy as sa


revision = "003_tenant_default_approvers"
down_revision = "002_contacts_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("default_approvers", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenants", "default_approvers")
