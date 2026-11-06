"""A lossy decode must not be advertised as an exact source snapshot."""

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock

from repoguide import indexer
from repoguide.git_utils import ClonedRepository
from repoguide.models import Chunk, SourceFile


def test_non_utf8_source_remains_partial_instead_of_replacement_snapshot(
    tmp_path, monkeypatch
):
    (tmp_path / "valid.py").write_text("def valid():\n    return 1\n")
    (tmp_path / "latin.py").write_bytes(b'def legacy():\n    return "\xff"\n')

    @contextmanager
    def clone(_):
        yield ClonedRepository(tmp_path, "a" * 40, "example", "fixture")

    monkeypatch.setattr(indexer, "clone_repository", clone)
    embedder = MagicMock()
    embedder.encode_documents.side_effect = lambda texts: [[0.0] * 384 for _ in texts]
    monkeypatch.setattr(indexer, "get_embedding_service", lambda: embedder)
    records = []
    db = MagicMock()
    db.scalar.return_value = None
    db.add.side_effect = records.append

    def flush():
        for record in records:
            if hasattr(record, "id") and record.id is None:
                record.id = str(uuid.uuid4())

    db.flush.side_effect = flush
    indexer.index_repository("https://github.com/example/fixture", db)
    snapshots = {r.path for r in records if isinstance(r, SourceFile)}
    assert "valid.py" in snapshots
    assert "latin.py" not in snapshots
    assert any(isinstance(r, Chunk) and r.file_path == "latin.py" for r in records)
