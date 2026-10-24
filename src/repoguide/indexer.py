from repoguide.telemetry import observed
from sqlalchemy import delete, select
from pathlib import Path
from typing import Callable
from sqlalchemy.orm import Session

from repoguide.embeddings import get_embedding_service
from repoguide.git_utils import clone_repository
from repoguide.intelligence import analyze_repository
from repoguide.chunking import parse_repository_m3
from repoguide.models import Chunk, CodeEdge, CodeSymbol, RepoDependency, Repository, SourceFile
from repoguide.parser import ParsedChunk, collect_source_files


def text_for_embedding(chunk: ParsedChunk) -> str:
    return (
        f"File: {chunk.file_path}\n"
        f"Symbol: {chunk.symbol_name or 'module'}\n"
        f"Type: {chunk.kind}\n\n{chunk.content}"
    )


@observed("index.repository", "RETRIEVER" if "retrieval" in "index.repository" else "CHAIN")

def index_repository(
    url: str, session: Session, *, force: bool = False,
    progress: Callable[[str, int, str], None] | None = None,
) -> Repository:
    def emit(stage: str, percent: int, detail: str) -> None:
        if progress:
            progress(stage, percent, detail)
    emit('cloning', 8, 'Fetching repository at its latest commit')
    with clone_repository(url) as clone:
        canonical_url = f"https://github.com/{clone.owner}/{clone.name}"
        existing = session.scalar(
            select(Repository).where(
                Repository.url == canonical_url,
                Repository.commit_sha == clone.commit_sha,
            )
        )

        emit('cloning', 24, f'Checked out {clone.commit_sha[:10]}')
        # Previously indexed Milestone 1 repositories need their graph backfilled.
        if existing and existing.status == "indexed" and not force:
            has_graph = session.scalar(
                select(CodeSymbol.id).where(CodeSymbol.repo_id == existing.id).limit(1)
            )
            if has_graph:
                emit('complete', 100, 'This commit was already indexed')
                return existing

        emit('parsing', 30, 'Extracting symbols and code relationships')
        analysis = analyze_repository(clone.path)
        chunks = parse_repository_m3(clone.path, analysis=analysis)
        if not chunks:
            raise ValueError("No supported source files found")
        emit('parsing', 43, f'Parsed {len(chunks)} code chunks, {len(analysis.symbols)} symbols')
        # Store bounded, exact source snapshots for Monaco. Previously indexed commits
        # can be refreshed with force=True; no more than the parser's file limits.
        snapshots = []
        for path in collect_source_files(clone.path):
            try:
                raw = path.read_bytes()
                snapshots.append((path.relative_to(clone.path).as_posix(),
                                  raw.decode('utf-8', errors='replace'), len(raw)))
            except (OSError, UnicodeError):
                continue
        # Also snapshot small dependency manifests for the dependency explorer.
        # These are intentionally not embedded as arbitrary source chunks.
        manifest_names = {'pyproject.toml', 'package.json', 'requirements.txt',
                          'Pipfile', 'Cargo.toml', 'go.mod', 'pom.xml'}
        existing_paths = {name for name, _, _ in snapshots}
        for file_path in clone.path.rglob('*'):
            if file_path.name not in manifest_names or file_path.is_symlink() or not file_path.is_file():
                continue
            relative = file_path.relative_to(clone.path)
            if any(part in {'.git','.venv','node_modules','dist','build'} for part in relative.parts):
                continue
            name = relative.as_posix()
            if name in existing_paths or len(snapshots) >= 2200:
                continue
            try:
                if file_path.stat().st_size > 150_000:
                    continue
                raw=file_path.read_bytes()
                snapshots.append((name,raw.decode('utf-8',errors='replace'),len(raw)))
                existing_paths.add(name)
            except OSError:
                continue
        embedder = get_embedding_service()
        embeddings = []
        emit('embedding', 48, f'Generating embeddings for {len(chunks)} chunks')
        for start in range(0, len(chunks), 32):
            batch = chunks[start : start + 32]
            embeddings.extend(
                embedder.encode_documents(
                    [text_for_embedding(chunk) for chunk in batch]
                )
            )
            emit('embedding', 48 + round(32 * min(len(chunks), start + 32) / len(chunks)),
                 f'Embedded {min(len(chunks), start + 32)}/{len(chunks)} chunks')

        emit('persisting', 83, 'Writing versioned code index and source snapshots')
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
                session.add(SourceFile(repo_id=repository.id, path=file_path,
                                       content=content, byte_count=byte_count))

            repository.status = "indexed"
            session.commit()
            session.refresh(repository)
            emit('complete', 100, f'Indexed {len(chunks)} chunks and {len(snapshots)} files')
            return repository
        except Exception:
            session.rollback()
            raise
