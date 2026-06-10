"""audit_events.tsa_timestamp — stage schema for RFC 3161 cryptographic timestamping

Revision ID: 009
Revises: 008
Create Date: 2026-06-09
"""

from alembic import op
import sqlalchemy as sa


revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_events",
        sa.Column("tsa_timestamp", sa.DateTime(), nullable=True),
    )
    # Indexed so the backfill job can cheaply find events not yet timestamped.
    op.create_index(
        "ix_audit_events_tsa_timestamp",
        "audit_events",
        ["tsa_timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_tsa_timestamp", table_name="audit_events")
    op.drop_column("audit_events", "tsa_timestamp")
