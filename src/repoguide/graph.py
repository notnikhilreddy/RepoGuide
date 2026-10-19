"""Graph-aware retrieval while keeping a fixed evidence budget."""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from repoguide.models import Chunk, CodeEdge, CodeSymbol
from repoguide.retriever import retrieve


@dataclass
class Evidence:
    chunk: Chunk
    origin: str  # dense or graph
    distance: float | None


def retrieve_with_graph(
    *, session: Session, repo_id: str, question: str, top_k: int = 8,
) -> list[Evidence]:
    vectors = retrieve(
        session=session, repo_id=repo_id, question=question, top_k=top_k
    )
    if not vectors:
        return []

    # Reserve part of the evidence budget for resolved callees.
    seed_count = max(1, (top_k * 5 + 7) // 8)
    seeds = vectors[:seed_count]
    chosen = [Evidence(v.chunk, "dense", v.distance) for v in seeds]
    seen = {v.chunk.id for v in seeds}

    source_symbols = []
    for vector in seeds:
        chunk = vector.chunk
        if not chunk.symbol_name:
            continue  # Module-level windows have no unambiguous symbol identity.
        symbol = session.scalar(
            select(CodeSymbol).where(
                CodeSymbol.repo_id == repo_id,
                CodeSymbol.file_path == chunk.file_path,
                CodeSymbol.qualified_name == chunk.symbol_name,
                CodeSymbol.start_line <= chunk.end_line,
                CodeSymbol.end_line >= chunk.start_line,
            ).order_by(CodeSymbol.start_line.desc()).limit(1)
        )
        if symbol and symbol.kind in {"function", "method"}:
            source_symbols.append(symbol.id)

    if source_symbols:
        edges = session.scalars(
            select(CodeEdge).where(
                CodeEdge.repo_id == repo_id,
                CodeEdge.kind == "calls",
                CodeEdge.source_symbol_id.in_(source_symbols),
                CodeEdge.target_symbol_id.is_not(None),
            ).order_by(CodeEdge.line).limit(50)
        ).all()

        for edge in edges:
            if len(chosen) >= top_k:
                break
            target = session.get(CodeSymbol, edge.target_symbol_id)
            if not target:
                continue
            query = select(Chunk).where(
                Chunk.repo_id == repo_id,
                Chunk.file_path == target.file_path,
                Chunk.start_line <= target.end_line,
                Chunk.end_line >= target.start_line,
            )
            if target.kind in {"function", "method"} and target.language == "python":
                query = query.where(Chunk.symbol_name == target.qualified_name)
            query = query.order_by(Chunk.start_line).limit(1)
            related = session.scalar(query)
            if related and related.id not in seen:
                chosen.append(Evidence(related, "graph", None))
                seen.add(related.id)

    for vector in vectors:
        if len(chosen) >= top_k:
            break
        if vector.chunk.id not in seen:
            chosen.append(Evidence(vector.chunk, "dense", vector.distance))
            seen.add(vector.chunk.id)

    return chosen
