"""tenants.email_verified_at

Revision ID: 004
Revises: 003
Create Date: 2026-05-26
"""

from alembic import op
import sqlalchemy as sa


revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("email_verified_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenants", "email_verified_at")
