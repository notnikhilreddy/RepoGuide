"""add chunks full text index

Revision ID: 7b395ac03aa0
Revises: 77f2cdd3e6e0
Create Date: 2026-10-21 12:26:43.463183

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7b395ac03aa0"
down_revision: Union[str, Sequence[str], None] = "77f2cdd3e6e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX ix_chunks_fts_simple
        ON chunks USING GIN (
            to_tsvector('simple'::regconfig,
                coalesce(file_path, '') || ' ' ||
                coalesce(symbol_name, '') || ' ' ||
                coalesce(content, '')
            )
        )
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_fts_simple")
