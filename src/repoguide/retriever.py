from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from repoguide.embeddings import get_embedding_service
from repoguide.models import Chunk


@dataclass
class RetrievedChunk:
    chunk: Chunk
    distance: float


def retrieve(
    *,
    session: Session,
    repo_id: str,
    question: str,
    top_k: int = 8,
) -> list[RetrievedChunk]:
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20")

    query_embedding = (
        get_embedding_service().encode_query(question)
    )

    distance = Chunk.embedding.cosine_distance(query_embedding)

    statement = (
        select(Chunk, distance.label("distance"))
        .where(Chunk.repo_id == repo_id)
        .order_by(distance)
        .limit(top_k)
    )

    rows = session.execute(statement).all()

    return [
        RetrievedChunk(
            chunk=row[0],
            distance=float(row[1]),
        )
        for row in rows
    ]