"""Tenant-scoped repository versions and ingestion diagnostics.

Revision ID: b42d92e7a610
Revises: 98cc72143f07
"""

from alembic import op
import sqlalchemy as sa

revision = "b42d92e7a610"
down_revision = "98cc72143f07"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "repositories",
        sa.Column("owner_sub", sa.String(128), nullable=False, server_default=""),
    )
    op.add_column(
        "repositories", sa.Column("parent_repo_id", sa.String(36), nullable=True)
    )
    op.add_column("repositories", sa.Column("index_metadata", sa.JSON(), nullable=True))
    op.drop_constraint("uq_repository_url_commit", "repositories", type_="unique")
    op.create_unique_constraint(
        "uq_repository_owner_url_commit",
        "repositories",
        ["owner_sub", "url", "commit_sha"],
    )


def downgrade():
    # Downgrade refuses duplicate tenant snapshots instead of deleting user data.
    op.create_unique_constraint(
        "uq_repository_url_commit", "repositories", ["url", "commit_sha"]
    )
    op.drop_constraint("uq_repository_owner_url_commit", "repositories", type_="unique")
    for column in ("index_metadata", "parent_repo_id", "owner_sub"):
        op.drop_column("repositories", column)
