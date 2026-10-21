"""Optional local pairwise re-ranker, loaded once on first use."""

from functools import lru_cache

from repoguide.config import settings


@lru_cache(maxsize=1)
def get_reranker():
    from sentence_transformers import CrossEncoder

    name = getattr(settings, "rerank_model", "cross-encoder/ms-marco-MiniLM-L6-v2")
    return CrossEncoder(name, max_length=512)
