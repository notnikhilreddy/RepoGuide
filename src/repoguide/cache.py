"""M5 Redis final-result caching. Only validated answers are cached.

Local-dev key namespace. Before multi-user production, use authenticated tenant
identity in the key, restrict Redis access, and define data retention rules.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache

from repoguide.config import settings


@lru_cache(maxsize=1)
def cache_client():
    import redis

    url = getattr(settings, "redis_url", "")
    if not url:
        return None
    return redis.Redis.from_url(
        url, decode_responses=True, socket_timeout=1, socket_connect_timeout=1
    )


def result_key(state: dict, provider: str, model: str) -> str:
    material = {
        "schema": "m5-v1",
        "question": state["question"],
        "repo_id": state["repo_id"],
        "commit": state.get("commit_sha"),
        "policy": state.get("docs_policy"),
        "sources": state.get("sources", []),
        "docs": state.get("external_evidence", []),
        "provider": provider,
        "model": model,
    }
    fingerprint = hashlib.sha256(
        json.dumps(material, sort_keys=True, default=str).encode()
    ).hexdigest()
    return "repoguide:local:m5:" + fingerprint


def load_result(key: str) -> dict | None:
    try:
        c = cache_client()
        return json.loads(value) if c and (value := c.get(key)) else None
    except Exception:
        return None  # optional cache should not make the API unavailable


def save_result(key: str, result: dict, ttl: int = 300) -> None:
    try:
        c = cache_client()
        if c:
            c.setex(key, ttl, json.dumps(result, default=str))
    except Exception:
        pass


def tool_cache_key(provider: str, query: dict) -> str:
    material = json.dumps(
        {"provider": provider, "query": query, "version": 1},
        sort_keys=True,
        default=str,
    )
    return "repoguide:local:tool:" + hashlib.sha256(material.encode()).hexdigest()


def load_tool(key: str) -> dict | None:
    return load_result(key)


def save_tool(key: str, value: dict, ttl: int = 3600) -> None:
    save_result(key, value, ttl=ttl)
