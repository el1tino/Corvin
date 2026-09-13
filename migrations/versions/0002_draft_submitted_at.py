"""record when a human submitted a draft to the authority

Revision ID: 0002_draft_submitted_at
Revises: 0001_initial
Create Date: 2026-09-13 00:00:00

"""

import sqlalchemy as sa
from alembic import op

revision = "0002_draft_submitted_at"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("drafts", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("drafts", "submitted_at")
