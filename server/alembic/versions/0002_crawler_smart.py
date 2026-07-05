"""crawler smart scheduling: job retries/timestamps, route_coverage, request_budgets

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-04

"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("crawl_jobs", sa.Column("retries", sa.Integer, nullable=False, server_default="0"))
    op.add_column(
        "crawl_jobs",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column(
        "crawl_jobs",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_crawl_jobs_claim", "crawl_jobs", ["status", "priority", "run_after"])

    op.create_table(
        "route_coverage",
        sa.Column("origin", sa.String(3), primary_key=True),
        sa.Column("dest", sa.String(3), primary_key=True),
        sa.Column("month", sa.Date, primary_key=True),
        sa.Column("source", sa.String(32), primary_key=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fail_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("demand_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("demand_updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "request_budgets",
        sa.Column("domain", sa.String(128), primary_key=True),
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("used", sa.Integer, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("request_budgets")
    op.drop_table("route_coverage")
    op.drop_index("ix_crawl_jobs_claim", table_name="crawl_jobs")
    op.drop_column("crawl_jobs", "updated_at")
    op.drop_column("crawl_jobs", "created_at")
    op.drop_column("crawl_jobs", "retries")
