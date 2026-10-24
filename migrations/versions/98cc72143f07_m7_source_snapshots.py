"""Persist safe source snapshots for the code explorer.

Revision ID: 98cc72143f07
Revises: 7b395ac03aa0
"""
from alembic import op
import sqlalchemy as sa

revision = '98cc72143f07'
down_revision = '7b395ac03aa0'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'source_files',
        sa.Column('repo_id', sa.String(length=36), nullable=False),
        sa.Column('path', sa.Text(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('byte_count', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['repo_id'], ['repositories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('repo_id','path'),
    )

def downgrade():
    op.drop_table('source_files')
