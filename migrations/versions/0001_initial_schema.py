"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-01-01 00:00:00

"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "customer_config",
        sa.Column("id", sa.String(length=20), primary_key=True),
        sa.Column("entity_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("member_state", sa.String(length=2), nullable=False, server_default=""),
        sa.Column("default_timezone", sa.String(length=64), nullable=False, server_default="Europe/Brussels"),
        sa.Column("dora_authority_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("dora_authority_contact", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("nis2_csirt_or_authority_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("nis2_csirt_or_authority_contact", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("gdpr_supervisory_authority_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("gdpr_supervisory_authority_contact", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("hosting_region", sa.String(length=50), nullable=False, server_default="EU"),
        sa.Column("allow_non_eu_llm", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "incidents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("source_system", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("source_reference", sa.String(length=200), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("awareness_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("classification_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("confirmed_by_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
    )

    op.create_table(
        "classification_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("incident_id", sa.String(length=36), sa.ForeignKey("incidents.id"), nullable=False),
        sa.Column("ruleset_versions", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("facts_snapshot", sa.JSON(), nullable=False),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confirmed_by_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_classification_runs_incident_id", "classification_runs", ["incident_id"])

    op.create_table(
        "drafts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("incident_id", sa.String(length=36), sa.ForeignKey("incidents.id"), nullable=False),
        sa.Column("framework", sa.String(length=20), nullable=False),
        sa.Column("stage", sa.String(length=30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("placeholders", sa.JSON(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("model_used", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exported_format", sa.String(length=10), nullable=True),
    )
    op.create_index("ix_drafts_incident_id", "drafts", ["incident_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.String(length=36), sa.ForeignKey("incidents.id"), nullable=True),
        sa.Column("actor_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor_label", sa.String(length=200), nullable=False, server_default="system"),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
    )
    op.create_index("ix_audit_events_incident_id", "audit_events", ["incident_id"])
    op.create_index("ix_audit_events_seq", "audit_events", ["seq"], unique=True)
    op.create_index("ix_audit_events_hash", "audit_events", ["hash"], unique=True)

    # Tamper-evidence at the database level, not just application
    # convention: once written, an audit event can never be changed or
    # removed, even by a client with direct SQL access. See
    # app/models/audit_event.py.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE RULE audit_events_no_update AS ON UPDATE TO audit_events DO INSTEAD NOTHING")
        op.execute("CREATE RULE audit_events_no_delete AS ON DELETE TO audit_events DO INSTEAD NOTHING")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP RULE IF EXISTS audit_events_no_delete ON audit_events")
        op.execute("DROP RULE IF EXISTS audit_events_no_update ON audit_events")
    op.drop_table("audit_events")
    op.drop_table("drafts")
    op.drop_table("classification_runs")
    op.drop_table("incidents")
    op.drop_table("customer_config")
    op.drop_table("users")
