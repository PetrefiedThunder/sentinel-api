"""approver contacts and notification attempts"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"


def upgrade():
    op.create_table(
        "approver_contacts",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("channel", sa.String, nullable=False),
        sa.Column("destination", sa.String, nullable=False),
        sa.Column("destination_hash", sa.String, nullable=False),
        sa.Column("destination_last4", sa.String, nullable=False),
        sa.Column("display_name", sa.String, nullable=True),
        sa.Column("consent_status", sa.String, nullable=False),
        sa.Column("consent_source", sa.String, nullable=False),
        sa.Column("consent_note", sa.Text, nullable=True),
        sa.Column("consented_at", sa.DateTime, nullable=True),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("tenant_id", "channel", "destination_hash", name="uq_approver_contact_destination"),
    )
    op.create_index("ix_approver_contacts_tenant_id", "approver_contacts", ["tenant_id"])
    op.create_index("ix_approver_contacts_destination_hash", "approver_contacts", ["destination_hash"])
    op.create_index("ix_approver_contacts_created_at", "approver_contacts", ["created_at"])

    op.create_table(
        "notification_attempts",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("action_id", sa.String, sa.ForeignKey("approvals.id"), nullable=True),
        sa.Column("contact_id", sa.String, sa.ForeignKey("approver_contacts.id"), nullable=True),
        sa.Column("channel", sa.String, nullable=False),
        sa.Column("destination_hash", sa.String, nullable=False),
        sa.Column("destination_last4", sa.String, nullable=False),
        sa.Column("provider", sa.String, nullable=False),
        sa.Column("provider_message_sid", sa.String, nullable=True),
        sa.Column("provider_status", sa.String, nullable=False),
        sa.Column("error_code", sa.String, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_notification_attempts_tenant_id", "notification_attempts", ["tenant_id"])
    op.create_index("ix_notification_attempts_action_id", "notification_attempts", ["action_id"])
    op.create_index("ix_notification_attempts_contact_id", "notification_attempts", ["contact_id"])
    op.create_index("ix_notification_attempts_destination_hash", "notification_attempts", ["destination_hash"])
    op.create_index("ix_notification_attempts_provider_message_sid", "notification_attempts", ["provider_message_sid"])
    op.create_index("ix_notification_attempts_created_at", "notification_attempts", ["created_at"])


def downgrade():
    op.drop_table("notification_attempts")
    op.drop_table("approver_contacts")
