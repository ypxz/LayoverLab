"""Unique partial index on active crawl jobs (dedupe concurrent enqueues)

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-05

"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

ACTIVE = "status IN ('pending', 'error')"


def upgrade() -> None:
    op.execute(
        "DELETE FROM crawl_jobs WHERE status IN ('pending', 'error') AND id NOT IN ("
        "SELECT MIN(id) FROM crawl_jobs WHERE status IN ('pending', 'error') "
        "GROUP BY connector, origin, dest, month)"
    )
    op.create_index(
        "uq_crawl_jobs_active",
        "crawl_jobs",
        ["connector", "origin", "dest", "month"],
        unique=True,
        postgresql_where=sa.text(ACTIVE),
        sqlite_where=sa.text(ACTIVE),
    )


def downgrade() -> None:
    op.drop_index("uq_crawl_jobs_active", table_name="crawl_jobs")
