"""initial schema"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None


def upgrade():
    op.create_table(
        "tenants",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("email", sa.String, unique=True, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("slack_team_id", sa.String, nullable=True),
        sa.Column("slack_bot_token", sa.String, nullable=True),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("key_hash", sa.String, nullable=False, index=True),
        sa.Column("prefix", sa.String, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
    )
    op.create_table(
        "approvals",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("function_name", sa.String, nullable=False),
        sa.Column("arguments", sa.JSON, nullable=False),
        sa.Column("risk_level", sa.String, nullable=False),
        sa.Column("approvers", sa.JSON, nullable=False),
        sa.Column("timeout_seconds", sa.Integer, nullable=False),
        sa.Column("decision", sa.String, nullable=False),
        sa.Column("decided_by", sa.String, nullable=True),
        sa.Column("decided_at", sa.DateTime, nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, index=True),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("action_id", sa.String, sa.ForeignKey("approvals.id"), index=True),
        sa.Column("execution_result", sa.String, nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("prev_hash", sa.String, nullable=True),
        sa.Column("event_hash", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, index=True),
    )


def downgrade():
    op.drop_table("audit_events")
    op.drop_table("approvals")
    op.drop_table("api_keys")
    op.drop_table("tenants")

