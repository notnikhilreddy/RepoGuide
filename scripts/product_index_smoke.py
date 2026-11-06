"""Exercise real PostgreSQL revision transactions with deterministic fixture vectors.

Only the disposable local database on 127.0.0.1:55432 is permitted. This is an
index consistency/reuse check, not a claim about live model or RAG quality.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

os.environ["DATABASE_URL"] = (
    "postgresql+psycopg://repoguide:repoguide@127.0.0.1:55432/repoguide?sslmode=require"
)
os.environ["MLFLOW_ENABLED"] = "false"

from sqlalchemy import delete, func, select

from repoguide import indexer
from repoguide.db import SessionLocal
from repoguide.git_utils import ClonedRepository
from repoguide.hybrid import SearchHit
from repoguide.models import Chunk, CodeSymbol, Repository, SourceFile
from repoguide.retrieval_context import supporting_source
from repoguide.retrieval_exact import exact_symbols


def main():
    owner = "product-smoke-" + uuid.uuid4().hex
    other = owner + "-other"
    records = []

    class Encoder:
        def encode_documents(self, texts):
            records.extend(texts)
            return [[0.1] + [0.0] * 383 for _ in texts]

    indexer.get_embedding_service = lambda: Encoder()
    sha = ["a" * 40]
    with tempfile.TemporaryDirectory(prefix="repoguide-index-smoke-") as directory:
        root = Path(directory)
        (root / "main.py").write_text(
            "from helper import normalize\n\ndef process(value):\n    return normalize(value)\n"
        )
        (root / "helper.py").write_text(
            "def normalize(value):\n    return value.strip()\n"
        )
        (root / "obsolete.py").write_text("def unused():\n    return 0\n")
        (root / "pyproject.toml").write_text(
            '[project]\nname="fixture"\nversion="0.1"\ndependencies=["fastapi>=0.1"]\n'
        )

        @contextmanager
        def clone(url, **kwargs):
            yield ClonedRepository(root, sha[0], "example", owner)

        indexer.clone_repository = clone
        url = "https://github.com/example/" + owner
        with SessionLocal() as db:
            try:
                first = indexer.index_repository(url, db, owner_sub=owner)
                first_id = first.id
                initial_calls = len(records)
                old_files = set(
                    db.scalars(
                        select(SourceFile.path).where(SourceFile.repo_id == first_id)
                    )
                )
                sha[0] = "b" * 40
                (root / "helper.py").write_text(
                    "def normalize(value):\n    return value.strip().lower()\n"
                )
                (root / "obsolete.py").unlink()
                (root / "routes.py").write_text(
                    "from main import process\n\ndef route(payload):\n    return process(payload)\n"
                )
                second = indexer.index_repository(
                    url, db, owner_sub=owner, base_repo_id=first_id
                )
                second_id = second.id
                metadata = second.index_metadata
                new_files = set(
                    db.scalars(
                        select(SourceFile.path).where(SourceFile.repo_id == second_id)
                    )
                )
                assert (
                    first_id != second_id
                    and "obsolete.py" in old_files
                    and "obsolete.py" not in new_files
                )
                assert (
                    "routes.py" in new_files
                    and metadata["reused_chunks"] > 0
                    and metadata["embedded_chunks"] > 0
                )
                assert (
                    metadata["deleted_files"] == 1
                    and metadata["added_files"] == 1
                    and metadata["modified_files"] == 1
                )
                assert len(records) - initial_calls == metadata["embedded_chunks"]
                assert (
                    db.scalar(
                        select(Repository.commit_sha).where(Repository.id == first_id)
                    )
                    == "a" * 40
                )
                assert not db.scalar(
                    select(CodeSymbol.id)
                    .where(
                        CodeSymbol.repo_id == second_id,
                        CodeSymbol.file_path == "obsolete.py",
                    )
                    .limit(1)
                )
                previous_count = db.scalar(
                    select(func.count())
                    .select_from(Chunk)
                    .where(Chunk.repo_id == second_id)
                )
                sha[0] = "c" * 40
                (root / "routes.py").write_text("def replacement():\n    return 42\n")

                def interrupt():
                    raise RuntimeError("Intentional pre-publication interruption")

                try:
                    indexer.index_repository(
                        url,
                        db,
                        owner_sub=owner,
                        base_repo_id=second_id,
                        commit_guard=interrupt,
                    )
                    raise AssertionError("The interruption was ignored")
                except RuntimeError as exc:
                    assert "Intentional" in str(exc)
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(Chunk)
                        .where(Chunk.repo_id == second_id)
                    )
                    == previous_count
                )
                assert not db.scalar(
                    select(Repository.id).where(
                        Repository.owner_sub == owner, Repository.commit_sha == "c" * 40
                    )
                )
                sha[0] = "b" * 40
                tenant = indexer.index_repository(url, db, owner_sub=other)
                assert tenant.id != second_id and tenant.owner_sub == other
                fixture_id = json.loads(Path(".artifacts/fixture.json").read_text())[
                    "repo_id"
                ]
                seed = db.scalar(
                    select(Chunk)
                    .where(
                        Chunk.repo_id == fixture_id,
                        Chunk.file_path == "src/repoguide/indexer.py",
                        Chunk.start_line.between(110, 150),
                    )
                    .order_by(Chunk.start_line.desc())
                    .limit(1)
                )
                tail = supporting_source(db, fixture_id, [SearchHit(seed, "fixture")])
                assert any("session.rollback()" in h.chunk.content for h in tail), (
                    "Function tails must expose rollback evidence"
                )
                embedding = db.scalar(
                    select(Chunk)
                    .where(
                        Chunk.repo_id == fixture_id,
                        Chunk.file_path == "src/repoguide/embeddings.py",
                        Chunk.start_line == 1,
                    )
                    .limit(1)
                )
                definitions = supporting_source(
                    db, fixture_id, [SearchHit(embedding, "fixture")]
                )
                assert any(
                    h.chunk.file_path == "src/repoguide/config.py"
                    and "384" in h.chunk.content
                    for h in definitions
                ), "Referenced settings need their repository definition"
                assert exact_symbols(
                    db, fixture_id, "Explain EmbeddingService and index_repository"
                ), "Unquoted code identifiers need exact symbol recall"
                report = {
                    "passed": True,
                    "store": "disposable local PostgreSQL",
                    "real_embeddings": False,
                    "revision_ids_distinct": True,
                    "unchanged_embeddings_reused": metadata["reused_chunks"],
                    "changed_chunks_embedded": metadata["embedded_chunks"],
                    "deleted_files_removed": True,
                    "old_revision_preserved": True,
                    "interrupted_publication_rolled_back": True,
                    "separate_tenant_index": True,
                    "function_tail_retrieval": True,
                    "referenced_configuration_retrieval": True,
                    "unquoted_identifier_retrieval": True,
                }
                output = Path(".artifacts/product-index-smoke.json")
                output.write_text(json.dumps(report, indent=2))
                print(json.dumps(report))
            finally:
                db.rollback()
                db.execute(
                    delete(Repository).where(Repository.owner_sub.in_([owner, other]))
                )
                db.commit()


if __name__ == "__main__":
    main()
