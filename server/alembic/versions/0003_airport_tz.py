"""airports.tz: IANA timezone per airport (joined from airportsdata by IATA)

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-05

"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("airports", sa.Column("tz", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("airports", "tz")
