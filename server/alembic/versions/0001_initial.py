"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-04

"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "airport_clusters",
        sa.Column("id", sa.String(8), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
    )
    op.create_table(
        "airports",
        sa.Column("iata", sa.String(3), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("city", sa.String(96), nullable=False, server_default=""),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("lat", sa.Float, nullable=False),
        sa.Column("lon", sa.Float, nullable=False),
        sa.Column("cluster_id", sa.String(8), sa.ForeignKey("airport_clusters.id"), nullable=True),
    )
    op.create_index("ix_airports_country_code", "airports", ["country_code"])
    op.create_index("ix_airports_cluster_id", "airports", ["cluster_id"])

    op.create_table(
        "ground_links",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("from_iata", sa.String(3), nullable=False),
        sa.Column("to_iata", sa.String(3), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("minutes", sa.Integer, nullable=False),
        sa.Column("price_cents", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
    )
    op.create_index("ix_ground_links_from_iata", "ground_links", ["from_iata"])
    op.create_index("ix_ground_links_to_iata", "ground_links", ["to_iata"])

    op.create_table(
        "routes",
        sa.Column("origin", sa.String(3), primary_key=True),
        sa.Column("dest", sa.String(3), primary_key=True),
        sa.Column("carriers", sa.JSON, nullable=False),
        sa.Column("frequency_score", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "fares",
        sa.Column("origin", sa.String(3), primary_key=True),
        sa.Column("dest", sa.String(3), primary_key=True),
        sa.Column("dep_date", sa.Date, primary_key=True),
        sa.Column("source", sa.String(32), primary_key=True),
        sa.Column("min_price_cents", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("deep_link", sa.Text, nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_fares_origin_date", "fares", ["origin", "dep_date"])
    op.create_index("ix_fares_dest_date", "fares", ["dest", "dep_date"])

    op.create_table(
        "crawl_jobs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("connector", sa.String(32), nullable=False),
        sa.Column("origin", sa.String(3), nullable=False),
        sa.Column("dest", sa.String(3), nullable=False),
        sa.Column("month", sa.Date, nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text, nullable=True),
    )
    op.create_index("ix_crawl_jobs_priority", "crawl_jobs", ["priority"])
    op.create_index("ix_crawl_jobs_status", "crawl_jobs", ["status"])

    op.create_table(
        "itineraries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
    )


def downgrade() -> None:
    for t in ["itineraries", "crawl_jobs", "fares", "routes", "ground_links", "airports", "airport_clusters"]:
        op.drop_table(t)
