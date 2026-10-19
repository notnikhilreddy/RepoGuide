from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from repoguide.embeddings import get_embedding_service
from repoguide.git_utils import clone_repository
from repoguide.intelligence import analyze_repository
from repoguide.models import Chunk, CodeEdge, CodeSymbol, RepoDependency, Repository
from repoguide.parser import ParsedChunk, parse_repository


def text_for_embedding(chunk: ParsedChunk) -> str:
    return (
        f"File: {chunk.file_path}\n"
        f"Symbol: {chunk.symbol_name or 'module'}\n"
        f"Type: {chunk.kind}\n\n{chunk.content}"
    )


def index_repository(url: str, session: Session) -> Repository:
    with clone_repository(url) as clone:
        canonical_url = f"https://github.com/{clone.owner}/{clone.name}"
        existing = session.scalar(select(Repository).where(
            Repository.url == canonical_url,
            Repository.commit_sha == clone.commit_sha,
        ))

        # Previously indexed Milestone 1 repositories need their graph backfilled.
        if existing and existing.status == "indexed":
            has_graph = session.scalar(
                select(CodeSymbol.id).where(CodeSymbol.repo_id == existing.id).limit(1)
            )
            if has_graph:
                return existing

        chunks = parse_repository(clone.path)
        if not chunks:
            raise ValueError("No supported source files found")
        analysis = analyze_repository(clone.path)
        embedder = get_embedding_service()
        embeddings = []
        for start in range(0, len(chunks), 32):
            batch = chunks[start:start + 32]
            embeddings.extend(embedder.encode_documents(
                [text_for_embedding(chunk) for chunk in batch]
            ))

        try:
            if existing:
                repository = existing
                for model in (CodeEdge, CodeSymbol, RepoDependency, Chunk):
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
                session.add(Chunk(
                    repo_id=repository.id,
                    file_path=parsed.file_path,
                    symbol_name=parsed.symbol_name,
                    kind=parsed.kind,
                    start_line=parsed.start_line,
                    end_line=parsed.end_line,
                    content=parsed.content,
                    embedding=vector,
                ))

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
                session.add(CodeEdge(
                    repo_id=repository.id,
                    source_symbol_id=by_draft_key[draft.source_key].id,
                    target_symbol_id=(
                        by_draft_key[draft.target_key].id if draft.target_key else None
                    ),
                    kind=draft.kind,
                    target_name=draft.target_name,
                    line=draft.line,
                ))

            for draft in analysis.dependencies:
                session.add(RepoDependency(
                    repo_id=repository.id,
                    name=draft.name,
                    spec=draft.spec,
                    manifest=draft.manifest,
                    group=draft.group,
                ))

            repository.status = "indexed"
            session.commit()
            session.refresh(repository)
            return repository
        except Exception:
            session.rollback()
            raise
