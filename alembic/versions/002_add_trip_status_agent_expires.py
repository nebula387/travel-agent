"""add trip start_date/status and agent_context expires_at

Revision ID: 002
Revises: 001
Create Date: 2026-05-09

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("trips", sa.Column("start_date", sa.Date(), nullable=True))
    op.add_column(
        "trips",
        sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
    )
    # rename trip_data → data for consistency (keep trip_data if exists)
    op.add_column("trips", sa.Column("data", sa.JSON(), nullable=True))

    op.add_column(
        "agent_contexts",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index("ix_trips_user_id", "trips", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_trips_user_id", "trips")
    op.drop_column("agent_contexts", "expires_at")
    op.drop_column("trips", "data")
    op.drop_column("trips", "status")
    op.drop_column("trips", "start_date")
