"""tenants.mode — live vs test workspace

Revision ID: 008
Revises: 007
Create Date: 2026-06-07
"""

from alembic import op
import sqlalchemy as sa


revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("mode", sa.String(), nullable=False, server_default="live"),
    )


def downgrade() -> None:
    op.drop_column("tenants", "mode")
