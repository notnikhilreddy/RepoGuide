"""Budget- and overlap-aware evidence selection for repository RAG."""

from __future__ import annotations

from dataclasses import dataclass

from repoguide.hybrid import SearchHit
from repoguide.telemetry import observed


@dataclass
class PackedHit:
    hit: SearchHit
    content: str
    end_line: int


def _overlaps_most_of_candidate(
    candidate: SearchHit, selected: list[PackedHit]
) -> bool:
    c = candidate.chunk
    candidate_length = max(1, c.end_line - c.start_line + 1)
    for prev in selected:
        p = prev.hit.chunk
        if p.file_path != c.file_path:
            continue
        intersection = max(
            0, min(c.end_line, prev.end_line) - max(c.start_line, p.start_line) + 1
        )
        if intersection / candidate_length >= 0.80:
            return True
    return False


@observed("retrieval.pack", "RETRIEVER")
def pack_context(
    hits: list[SearchHit],
    *,
    max_chars: int = 16000,
    per_chunk_chars: int = 3000,
) -> list[PackedHit]:
    """Prevent overlapping chunks from crowding out distinct evidence.

    Budget is measured in characters, *not* model tokens. For strict model
    context-length safety, replace with provider-specific tokenizer counting.
    """
    if max_chars <= 0 or per_chunk_chars <= 0:
        raise ValueError("Context budgets must be positive")
    selected: list[PackedHit] = []
    used = 0
    for hit in hits:
        if _overlaps_most_of_candidate(hit, selected):
            continue
        c = hit.chunk
        metadata_budget = len(c.file_path) + len(c.symbol_name or "") + 130
        available = min(per_chunk_chars, max_chars - used - metadata_budget)
        if available < 80:
            break

        # Never cut a line halfway through. This makes returned end_line accurate.
        lines: list[str] = []
        chars = 0
        for line in c.content.splitlines():
            if chars + len(line) + 1 > available:
                break
            lines.append(line)
            chars += len(line) + 1
        if not lines:
            continue
        selected.append(
            PackedHit(
                hit=hit,
                content="\n".join(lines),
                end_line=min(c.end_line, c.start_line + len(lines) - 1),
            )
        )
        used += metadata_budget + chars
    return selected
