from sqlalchemy import select
from sqlalchemy.orm import Session

from repoguide.embeddings import get_embedding_service
from repoguide.git_utils import clone_repository
from repoguide.models import Chunk, Repository
from repoguide.parser import ParsedChunk, parse_repository


def text_for_embedding(chunk: ParsedChunk) -> str:
    return (
        f"File: {chunk.file_path}\n"
        f"Symbol: {chunk.symbol_name or 'module'}\n"
        f"Type: {chunk.kind}\n\n"
        f"{chunk.content}"
    )


def index_repository(url: str, session: Session) -> Repository:
    with clone_repository(url) as clone:
        canonical_url = (
            f"https://github.com/{clone.owner}/{clone.name}"
        )

        existing = session.scalar(
            select(Repository).where(
                Repository.url == canonical_url,
                Repository.commit_sha == clone.commit_sha,
            )
        )

        if existing is not None and existing.status == "indexed":
            return existing

        parsed_chunks = parse_repository(clone.path)

        if not parsed_chunks:
            raise ValueError("No supported source files found")

        embedding_service = get_embedding_service()
        embeddings = []

        for start in range(0, len(parsed_chunks), 32):
            batch = parsed_chunks[start:start + 32]

            texts = [
                text_for_embedding(chunk)
                for chunk in batch
            ]

            embeddings.extend(
                embedding_service.encode_documents(texts)
            )

        try:
            if existing is None:
                repository = Repository(
                    url=canonical_url,
                    commit_sha=clone.commit_sha,
                    status="indexing",
                )
                session.add(repository)
                session.flush()
            else:
                repository = existing

                session.query(Chunk).filter(
                    Chunk.repo_id == repository.id
                ).delete(synchronize_session=False)

            for parsed, embedding in zip(
                parsed_chunks, embeddings, strict=True
            ):
                session.add(
                    Chunk(
                        repo_id=repository.id,
                        file_path=parsed.file_path,
                        symbol_name=parsed.symbol_name,
                        kind=parsed.kind,
                        start_line=parsed.start_line,
                        end_line=parsed.end_line,
                        content=parsed.content,
                        embedding=embedding,
                    )
                )

            repository.status = "indexed"

            session.commit()
            session.refresh(repository)

            return repository

        except Exception:
            session.rollback()
            raise