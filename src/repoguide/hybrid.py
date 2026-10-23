"""RepoGuide M3: PostgreSQL lexical search, RRF fusion, optional graph and reranking.

Maintains Milestone 1/2 retrieval APIs and requires no external search service.
"""

from __future__ import annotations
from repoguide.telemetry import observed

from dataclasses import dataclass
import re

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from repoguide.graph import retrieve_with_graph
from repoguide.models import Chunk
from repoguide.retriever import retrieve


# Must match the index expression in migrations_examples/fts_migration.py.
# PostgreSQL 'simple' dictionary preserves code vocabulary better than English
# stemming for identifiers, although it is not an exact-symbol substring index.
FTS_SQL = """
WITH q AS (
    SELECT to_tsquery('simple'::regconfig, :terms) AS query
)
SELECT chunks.id AS id,
       ts_rank_cd(
           to_tsvector('simple'::regconfig,
               coalesce(chunks.file_path, '') || ' ' ||
               coalesce(chunks.symbol_name, '') || ' ' ||
               coalesce(chunks.content, '')
           ), q.query
       ) AS score
FROM chunks CROSS JOIN q
WHERE chunks.repo_id = :repo_id
  AND to_tsvector('simple'::regconfig,
          coalesce(chunks.file_path, '') || ' ' ||
          coalesce(chunks.symbol_name, '') || ' ' ||
          coalesce(chunks.content, '')
      ) @@ q.query
ORDER BY score DESC, chunks.id
LIMIT :limit
"""


@dataclass
class SearchHit:
    chunk: Chunk
    origin: str
    distance: float | None = None
    fusion_score: float | None = None
    rerank_score: float | None = None
    channels: tuple[str, ...] = ()


STOP_WORDS = {
    "a",
    "about",
    "all",
    "an",
    "and",
    "are",
    "by",
    "can",
    "do",
    "does",
    "for",
    "from",
    "how",
    "in",
    "into",
    "is",
    "it",
    "me",
    "of",
    "on",
    "or",
    "our",
    "the",
    "their",
    "these",
    "this",
    "to",
    "using",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "would",
    "you",
    "your",
    "implemented",
    "implementation",
    "find",
    "show",
    "explain",
    "located",
    "defined",
}


def lexical_terms(question: str) -> str:
    """Make a safe OR-tsquery from meaningful query tokens (max 12).

    SQL parameters are still bound; the user text is NEVER interpolated into SQL.
    OR provides recall on long natural-language questions that otherwise would
    require every query word to occur in one chunk.
    """
    words = re.findall(r"[A-Za-z_][A-Za-z_0-9]{1,49}", question.lower())
    unique = []
    for word in words:
        if word not in STOP_WORDS and word not in unique:
            unique.append(word)
    return " | ".join(unique[:12])


@observed("retrieval.keyword", "RETRIEVER" if "retrieval" in "retrieval.keyword" else "CHAIN")

def keyword_retrieve(
    *,
    session: Session,
    repo_id: str,
    question: str,
    top_k: int = 24,
) -> list[SearchHit]:
    """Rank lexical candidates inside one repository with PostgreSQL FTS."""
    if top_k < 1:
        raise ValueError("top_k must be positive")
    if not question.strip():
        return []
    terms = lexical_terms(question)
    if not terms:
        return []
    rows = session.execute(
        text(FTS_SQL),
        {"repo_id": repo_id, "terms": terms, "limit": top_k},
    ).all()
    ids = [str(row.id) for row in rows]
    if not ids:
        return []
    # ORM load in one additional query; restore FTS rank order afterward.
    objects = session.scalars(
        select(Chunk).where(Chunk.repo_id == repo_id, Chunk.id.in_(ids))
    ).all()
    by_id = {c.id: c for c in objects}
    return [
        SearchHit(by_id[chunk_id], "keyword", channels=("keyword",))
        for chunk_id in ids
        if chunk_id in by_id
    ]


@observed("retrieval.rrf", "RETRIEVER" if "retrieval" in "retrieval.rrf" else "CHAIN")

def rrf_fuse(
    rankings: list[tuple[str, list[SearchHit]]],
    *,
    rrf_k: int = 60,
    weights: dict[str, float] | None = None,
) -> list[SearchHit]:
    """Weighted reciprocal rank fusion over chunk IDs; no incompatible score mixing.

    RRF(c) = sum(weight[channel] / (rrf_k + rank[channel])).
    Duplicate chunk IDs in a ranking are counted once.
    """
    if rrf_k < 1:
        raise ValueError("rrf_k must be positive")
    weights = weights or {}
    scores: dict[str, float] = {}
    chunks: dict[str, Chunk] = {}
    distances: dict[str, float] = {}
    origins: dict[str, set[str]] = {}
    best_ranks: dict[str, int] = {}

    for channel, hits in rankings:
        seen_in_channel: set[str] = set()
        rank = 0
        for hit in hits:
            cid = hit.chunk.id
            if cid in seen_in_channel:
                continue
            seen_in_channel.add(cid)
            rank += 1
            chunks[cid] = hit.chunk
            scores[cid] = scores.get(cid, 0.0) + weights.get(channel, 1.0) / (
                rrf_k + rank
            )
            origins.setdefault(cid, set()).add(channel)
            best_ranks[cid] = min(best_ranks.get(cid, rank), rank)
            if hit.distance is not None:
                distances[cid] = hit.distance

    ordered = sorted(scores, key=lambda cid: (-scores[cid], best_ranks[cid], cid))
    return [
        SearchHit(
            chunk=chunks[cid],
            origin="hybrid",
            distance=distances.get(cid),
            fusion_score=scores[cid],
            channels=tuple(sorted(origins[cid])),
        )
        for cid in ordered
    ]


@observed("retrieval.rerank", "RETRIEVER" if "retrieval" in "retrieval.rerank" else "CHAIN")

def rerank_hits(question: str, hits: list[SearchHit]) -> list[SearchHit]:
    """Cross-encoder reranking only for candidates already retrieved."""
    if not hits:
        return []
    from repoguide.reranker import get_reranker  # no model download on other modes

    model = get_reranker()
    pairs = [
        (
            question,
            f"File: {hit.chunk.file_path}\n"
            f"Symbol: {hit.chunk.symbol_name or 'module'}\n"
            f"{hit.chunk.content[:2600]}",
        )
        for hit in hits
    ]
    scores = model.predict(pairs, batch_size=16, show_progress_bar=False)
    for hit, score in zip(hits, scores, strict=True):
        hit.rerank_score = float(score)
    return sorted(
        hits,
        key=lambda hit: (-(hit.rerank_score or 0.0), -(hit.fusion_score or 0.0)),
    )


@observed("retrieval.search", "RETRIEVER" if "retrieval" in "retrieval.search" else "CHAIN")

def search(
    *,
    session: Session,
    repo_id: str,
    question: str,
    top_k: int = 8,
    retrieval_mode: str = "hybrid",
    candidate_k: int = 32,
    rrf_k: int = 60,
) -> list[SearchHit]:
    """Four baselines + optional graph variants, all with the same final top_k."""
    modes = {
        "dense",
        "graph",
        "keyword",
        "hybrid",
        "hybrid_rerank",
        "hybrid_graph",
        "hybrid_graph_rerank",
    }
    if retrieval_mode not in modes:
        raise ValueError(f"Unknown retrieval mode: {retrieval_mode}")
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be in [1, 20]")
    candidate_k = max(top_k, min(int(candidate_k), 80))

    if retrieval_mode == "dense":
        return [
            SearchHit(x.chunk, "dense", x.distance, channels=("dense",))
            for x in retrieve(
                session=session, repo_id=repo_id, question=question, top_k=top_k
            )
        ]
    if retrieval_mode == "graph":
        return [
            SearchHit(x.chunk, x.origin, x.distance, channels=(x.origin,))
            for x in retrieve_with_graph(
                session=session, repo_id=repo_id, question=question, top_k=top_k
            )
        ]
    if retrieval_mode == "keyword":
        return keyword_retrieve(
            session=session, repo_id=repo_id, question=question, top_k=top_k
        )

    dense_hits = [
        SearchHit(x.chunk, "dense", x.distance, channels=("dense",))
        for x in retrieve(
            session=session, repo_id=repo_id, question=question, top_k=candidate_k
        )
    ]
    lexical_hits = keyword_retrieve(
        session=session, repo_id=repo_id, question=question, top_k=candidate_k
    )
    rankings = [("dense", dense_hits), ("keyword", lexical_hits)]

    if "graph" in retrieval_mode:
        # M2 graph retrieval internally runs dense retrieval. This simple version
        # does duplicate some work; benchmark latency before optimizing.
        graph_hits = [
            SearchHit(x.chunk, x.origin, x.distance, channels=("graph",))
            for x in retrieve_with_graph(
                session=session,
                repo_id=repo_id,
                question=question,
                top_k=min(candidate_k, 20),
            )
            if x.origin == "graph"
        ]
        rankings.append(("graph", graph_hits))

    fused = rrf_fuse(rankings, rrf_k=rrf_k, weights={"graph": 0.7})
    if "rerank" in retrieval_mode:
        fused = rerank_hits(question, fused[:candidate_k])
    return fused[:top_k]
