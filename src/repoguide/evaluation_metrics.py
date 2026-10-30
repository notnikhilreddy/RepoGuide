"""Deterministic, testable file-level and citation metrics (no judge calls)."""

from __future__ import annotations

import re


def hit_at_k(expected: list[str], ranked: list[str], k: int) -> float:
    return float(bool(set(expected) & set(ranked[:k])))


def file_recall(expected: list[str], ranked: list[str], k: int) -> float:
    unique = set(expected)
    return len(unique & set(ranked[:k])) / len(unique) if unique else 1.0


def mrr(expected: list[str], ranked: list[str], k: int) -> float:
    good = set(expected)
    return next((1 / i for i, path in enumerate(ranked[:k], 1) if path in good), 0.0)


def citations_ok(answer: str, sources: list[dict]) -> bool:
    used = set(re.findall(r"\[([SD]\d+)\]", answer))
    available = {s["label"] for s in sources}
    return bool(used) and used.issubset(available)


def routing_correct(expected: list[str], observed: list[str]) -> bool:
    return set(expected) == set(observed)
