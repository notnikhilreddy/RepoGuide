"""Optional read-only PostgreSQL integration test.

Run with a real already-indexed repository ID:
REPOGUIDE_TEST_REPO_ID=<id> uv run pytest tests/test_m3_postgres_integration.py -v
"""

import os

import pytest
from sqlalchemy import text

from repoguide.db import SessionLocal
from repoguide.hybrid import keyword_retrieve


@pytest.mark.skipif(
    not os.getenv("REPOGUIDE_TEST_REPO_ID"),
    reason="Set REPOGUIDE_TEST_REPO_ID for PostgreSQL integration test",
)
def test_keyword_sql_and_existing_fts_index():
    with SessionLocal() as session:
        exists = session.scalar(
            text("""
            SELECT count(*) FROM pg_indexes
            WHERE tablename = 'chunks' AND indexname = 'ix_chunks_fts_simple'
        """)
        )
        assert exists == 1, "Alembic full-text search migration not applied"
        hits = keyword_retrieve(
            session=session,
            repo_id=os.environ["REPOGUIDE_TEST_REPO_ID"],
            question="repository indexing",
        )
        assert isinstance(hits, list)
        assert all(
            hit.chunk.repo_id == os.environ["REPOGUIDE_TEST_REPO_ID"] for hit in hits
        )
