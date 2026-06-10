"""uptime_probes — store status-probe results for /status uptime history

Revision ID: 010
Revises: 009
Create Date: 2026-06-09
"""

from alembic import op
import sqlalchemy as sa


revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "uptime_probes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("region", sa.String(), nullable=False),
        sa.Column("target", sa.String(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index("ix_uptime_probes_region", "uptime_probes", ["region"])
    op.create_index("ix_uptime_probes_created_at", "uptime_probes", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_uptime_probes_created_at", table_name="uptime_probes")
    op.drop_index("ix_uptime_probes_region", table_name="uptime_probes")
    op.drop_table("uptime_probes")
