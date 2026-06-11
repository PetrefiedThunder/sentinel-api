"""consumed_decision_nonces table — replay protection for signed decision links

Revision ID: 011
Revises: 010
Create Date: 2026-06-11
"""

from alembic import op
import sqlalchemy as sa


revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consumed_decision_nonces",
        # SHA-256 hex of the presented token — raw token is never stored.
        sa.Column("nonce", sa.String(length=64), nullable=False),
        sa.Column("action_id", sa.String(), sa.ForeignKey("approvals.id"), nullable=False),
        sa.Column(
            "consumed_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("nonce"),
    )
    op.create_index(
        "ix_consumed_decision_nonces_action_id",
        "consumed_decision_nonces",
        ["action_id"],
    )
    op.create_index(
        "ix_consumed_decision_nonces_consumed_at",
        "consumed_decision_nonces",
        ["consumed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_consumed_decision_nonces_consumed_at", table_name="consumed_decision_nonces"
    )
    op.drop_index(
        "ix_consumed_decision_nonces_action_id", table_name="consumed_decision_nonces"
    )
    op.drop_table("consumed_decision_nonces")
