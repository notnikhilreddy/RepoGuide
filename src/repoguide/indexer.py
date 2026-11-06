import json
import os
import time
from pathlib import Path
from typing import Callable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from repoguide.chunking import parse_repository_m3
from repoguide.config import settings
from repoguide.embeddings import get_embedding_service
from repoguide.git_utils import clone_repository
from repoguide.intelligence import analyze_repository
from repoguide.models import (
    Chunk,
    CodeEdge,
    CodeSymbol,
    RepoDependency,
    Repository,
    SourceFile,
)
from repoguide.parser import ParsedChunk, collect_source_files
from repoguide.telemetry import observed


def embedding_identity():
    path = Path("/opt/repoguide/release-config.json")
    if not path.exists():
        path = Path(__file__).resolve().parents[2] / "deployment/release-config.json"
    config = json.loads(path.read_text()) if path.exists() else {}
    return {
        "model": settings.embedding_model,
        "dimension": settings.embedding_dim,
        "revision": config.get("models", {}).get("embedding", {}).get("revision"),
    }


def text_for_embedding(chunk: ParsedChunk) -> str:
    return (
        f"File: {chunk.file_path}\n"
        f"Symbol: {chunk.symbol_name or 'module'}\n"
        f"Type: {chunk.kind}\n\n{chunk.content}"
    )


@observed("index.repository", "CHAIN")
def index_repository(
    url: str,
    session: Session,
    *,
    force: bool = False,
    progress: Callable[[str, int, str], None] | None = None,
    commit_sha: str | None = None,
    commit_guard: Callable[[], None] | None = None,
    owner_sub: str = "",
    base_repo_id: str | None = None,
    branch: str | None = None,
) -> Repository:
    def emit(stage: str, percent: int, detail: str) -> None:
        if progress:
            progress(stage, percent, detail)

    started = time.monotonic()
    clone_options = {}
    if commit_sha:
        clone_options["commit_sha"] = commit_sha
    if branch:
        clone_options["branch"] = branch
    base = session.get(Repository, base_repo_id) if base_repo_id else None
    if base_repo_id and (base is None or base.owner_sub != owner_sub):
        raise ValueError("Incremental base is not owned by this account")
    emit("cloning", 8, "Fetching repository at the selected revision")
    with clone_repository(url, **clone_options) as clone:
        canonical_url = f"https://github.com/{clone.owner}/{clone.name}"
        existing = session.scalar(
            select(Repository).where(
                Repository.url == canonical_url,
                Repository.commit_sha == clone.commit_sha,
                Repository.owner_sub == owner_sub,
            )
        )

        emit("cloning", 24, f"Checked out {clone.commit_sha[:10]}")
        # Previously indexed Milestone 1 repositories need their graph backfilled.
        if existing and existing.status == "indexed" and not force:
            has_graph = session.scalar(
                select(CodeSymbol.id).where(CodeSymbol.repo_id == existing.id).limit(1)
            )
            if has_graph:
                emit("complete", 100, "This commit was already indexed")
                return existing

        emit("parsing", 30, "Extracting symbols and code relationships")
        analysis = analyze_repository(clone.path)
        chunks = parse_repository_m3(clone.path, analysis=analysis)
        if not chunks:
            raise ValueError("No supported source files found")
        if len(chunks) > 12000:
            raise ValueError("Repository exceeds the demo's 12,000-chunk limit")
        emit(
            "parsing",
            43,
            f"Parsed {len(chunks)} code chunks, {len(analysis.symbols)} symbols",
        )
        # Store bounded, exact source snapshots for Monaco. Previously indexed commits
        # can be refreshed with force=True; no more than the parser's file limits.
        snapshots = []
        diagnostics = {}
        failed_files = []
        for path in collect_source_files(clone.path, diagnostics=diagnostics):
            try:
                raw = path.read_bytes()
                snapshots.append(
                    (
                        path.relative_to(clone.path).as_posix(),
                        raw.decode("utf-8"),
                        len(raw),
                    )
                )
            except (OSError, UnicodeError) as exc:
                failed_files.append(
                    {
                        "path": path.relative_to(clone.path).as_posix(),
                        "reason": type(exc).__name__,
                    }
                )
                continue
        # Also snapshot small dependency manifests for the dependency explorer.
        # These are intentionally not embedded as arbitrary source chunks.
        manifest_names = {
            "pyproject.toml",
            "package.json",
            "requirements.txt",
            "Pipfile",
            "Cargo.toml",
            "go.mod",
            "pom.xml",
        }
        existing_paths = {name for name, _, _ in snapshots}
        for file_path in clone.path.rglob("*"):
            if (
                file_path.name not in manifest_names
                or file_path.is_symlink()
                or not file_path.is_file()
            ):
                continue
            relative = file_path.relative_to(clone.path)
            if any(
                part in {".git", ".venv", "node_modules", "dist", "build"}
                for part in relative.parts
            ):
                continue
            name = relative.as_posix()
            if name in existing_paths or len(snapshots) >= 2200:
                continue
            try:
                if file_path.stat().st_size > 150_000:
                    continue
                raw = file_path.read_bytes()
                snapshots.append((name, raw.decode("utf-8"), len(raw)))
                existing_paths.add(name)
            except (OSError, UnicodeError):
                continue
        reusable = {}
        if os.getenv("REPOGUIDE_CLOUD_MODE") == "true" and (
            len(chunks) > 5000 or diagnostics.get("source_bytes", 0) > 10000000
        ):
            raise ValueError(
                "Public demo indexes are limited to 10 MB of supported source and 5,000 chunks"
            )
        old_paths = set()
        if base and base.url != canonical_url:
            raise ValueError("Incremental base belongs to a different repository")
        old_sources = {}
        if base:
            old_sources = {
                s.path: s.content
                for s in session.scalars(
                    select(SourceFile).where(SourceFile.repo_id == base.id)
                ).all()
            }
            old_paths = set(old_sources)
        identity = embedding_identity()
        compatible_base = bool(
            base
            and base.url == canonical_url
            and (base.index_metadata or {}).get("embedding_identity") == identity
        )
        if compatible_base:
            previous = session.scalars(
                select(Chunk).where(Chunk.repo_id == base.id)
            ).all()
            for old in previous:
                reusable[(old.file_path, old.symbol_name, old.kind, old.content)] = (
                    old.embedding
                )
                old_paths.add(old.file_path)
        embeddings = [None] * len(chunks)
        needed = []
        for pos, chunk in enumerate(chunks):
            vector = reusable.get(
                (chunk.file_path, chunk.symbol_name, chunk.kind, chunk.content)
            )
            if vector is not None:
                embeddings[pos] = vector
            else:
                needed.append(pos)
        embedder = get_embedding_service()
        emit("embedding", 48, f"Generating embeddings for {len(chunks)} chunks")
        for start in range(0, len(needed), 32):
            indices = needed[start : start + 32]
            vectors = embedder.encode_documents(
                [text_for_embedding(chunks[i]) for i in indices]
            )
            for pos, vector in zip(indices, vectors, strict=True):
                embeddings[pos] = vector
            emit(
                "embedding",
                48 + round(32 * min(len(needed), start + 32) / max(1, len(needed))),
                f"Embedded {min(len(needed), start + 32)}/{len(needed)} changed chunks; reused {len(chunks) - len(needed)}",
            )

        emit("persisting", 83, "Writing versioned code index and source snapshots")
        try:
            if existing:
                repository = existing
                for model in (CodeEdge, CodeSymbol, RepoDependency, Chunk, SourceFile):
                    session.execute(delete(model).where(model.repo_id == repository.id))
                session.flush()
            else:
                repository = Repository(
                    url=canonical_url,
                    commit_sha=clone.commit_sha,
                    status="indexing",
                    owner_sub=owner_sub,
                    parent_repo_id=base_repo_id,
                )
                session.add(repository)
                session.flush()

            for parsed, vector in zip(chunks, embeddings, strict=True):
                session.add(
                    Chunk(
                        repo_id=repository.id,
                        file_path=parsed.file_path,
                        symbol_name=parsed.symbol_name,
                        kind=parsed.kind,
                        start_line=parsed.start_line,
                        end_line=parsed.end_line,
                        content=parsed.content,
                        embedding=vector,
                    )
                )

            by_draft_key = {}
            for draft in analysis.symbols:
                record = CodeSymbol(
                    repo_id=repository.id,
                    file_path=draft.file_path,
                    language=draft.language,
                    name=draft.name,
                    qualified_name=draft.qualified_name,
                    kind=draft.kind,
                    start_line=draft.start_line,
                    end_line=draft.end_line,
                )
                session.add(record)
                by_draft_key[draft.key] = record

            session.flush()  # Materialize generated SQLAlchemy primary keys.

            for draft in analysis.edges:
                session.add(
                    CodeEdge(
                        repo_id=repository.id,
                        source_symbol_id=by_draft_key[draft.source_key].id,
                        target_symbol_id=(
                            by_draft_key[draft.target_key].id
                            if draft.target_key
                            else None
                        ),
                        kind=draft.kind,
                        target_name=draft.target_name,
                        line=draft.line,
                    )
                )

            for draft in analysis.dependencies:
                session.add(
                    RepoDependency(
                        repo_id=repository.id,
                        name=draft.name,
                        spec=draft.spec,
                        manifest=draft.manifest,
                        group=draft.group,
                    )
                )

            for file_path, content, byte_count in snapshots:
                session.add(
                    SourceFile(
                        repo_id=repository.id,
                        path=file_path,
                        content=content,
                        byte_count=byte_count,
                    )
                )

            repository.status = "indexed"
            new_paths = {c.file_path for c in chunks}
            chunk_paths = new_paths
            repository.index_metadata = {
                "indexed_files": len(snapshots),
                "chunks": len(chunks),
                "embedded_chunks": len(needed),
                "reused_chunks": len(chunks) - len(needed),
                "added_files": len(set(p for p, _, _ in snapshots) - old_paths)
                if base
                else len(snapshots),
                "modified_files": sum(
                    p in old_sources and old_sources[p] != content
                    for p, content, _ in snapshots
                ),
                "deleted_files": len(old_paths - set(p for p, _, _ in snapshots))
                if base
                else 0,
                "failed_files": failed_files,
                "embedding_identity": identity,
                **diagnostics,
                "warnings": [
                    f"No searchable chunks extracted from {p}"
                    for p, _, _ in snapshots
                    if p not in chunk_paths
                ][:50],
                "incremental": bool(base),
                "fallback_reason": None
                if compatible_base
                else "Previous index lacks compatible embedding provenance; all chunks embedded"
                if base
                else "Initial index",
                "graph_strategy": "Relationships rebuilt from the complete target snapshot; unchanged embeddings reused",
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
            if commit_guard:
                commit_guard()
            session.commit()
            session.refresh(repository)
            emit(
                "complete",
                100,
                f"Indexed {len(chunks)} chunks and {len(snapshots)} files",
            )
            return repository
        except Exception:
            session.rollback()
            raise
