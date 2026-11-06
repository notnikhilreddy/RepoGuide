"""Bounded conversational resolution, source focus and graph-neighbor expansion."""

from __future__ import annotations

import hashlib
import json
import re

from sqlalchemy import or_, select

from repoguide.hybrid import SearchHit
from repoguide.models import Chunk, CodeEdge, CodeSymbol, SourceFile


def bounded_history(history):
    result = []
    for item in (history or [])[-6:]:
        if item.get("role") in {"user", "assistant"} and isinstance(
            item.get("content"), str
        ):
            result.append(
                {
                    "role": item["role"],
                    "content": item["content"][:1200],
                    "paths": [
                        p[:300] for p in item.get("paths", [])[:5] if isinstance(p, str)
                    ],
                }
            )
    while len(json.dumps(result)) > 4500:
        result.pop(0)
    return result


def retrieval_question(question, history, focus):
    # Current intent remains first. Only the latest topic and cited paths guide
    # retrieval; past model prose is never treated as authoritative evidence.
    previous = next(
        (h["content"] for h in reversed(history) if h["role"] == "user"), ""
    )
    paths = list(dict.fromkeys(p for h in history for p in h.get("paths", [])))[:4]
    context = " ".join([str(focus.get("path", "")), previous[:300], *paths])
    return question + (
        "\nConversation/source context: " + context[:700] if context.strip() else ""
    )


def focused_chunks(session, repo_id, focus):
    if not focus.get("path"):
        return []
    statement = select(Chunk).where(
        Chunk.repo_id == repo_id, Chunk.file_path == focus["path"]
    )
    if focus.get("start_line"):
        statement = statement.where(
            Chunk.start_line <= focus.get("end_line", focus["start_line"]),
            Chunk.end_line >= focus["start_line"],
        )
    rows = session.scalars(statement.order_by(Chunk.start_line).limit(4)).all()
    return [SearchHit(c, "source_context", channels=("source_context",)) for c in rows]


def neighbors(session, repo_id, seeds, limit=8):
    if not seeds:
        return []
    paths = list(dict.fromkeys(h.chunk.file_path for h in seeds[:4]))
    symbols = session.scalars(
        select(CodeSymbol)
        .where(CodeSymbol.repo_id == repo_id, CodeSymbol.file_path.in_(paths))
        .order_by(CodeSymbol.file_path, CodeSymbol.start_line)
        .limit(160)
    ).all()
    ids = {
        s.id
        for s in symbols
        if any(
            h.chunk.file_path == s.file_path
            and h.chunk.start_line <= s.end_line
            and h.chunk.end_line >= s.start_line
            for h in seeds[:4]
        )
    }
    if not ids:
        return []
    edges = session.scalars(
        select(CodeEdge)
        .where(
            CodeEdge.repo_id == repo_id,
            CodeEdge.kind != "contains",
            CodeEdge.target_symbol_id.is_not(None),
            or_(CodeEdge.source_symbol_id.in_(ids), CodeEdge.target_symbol_id.in_(ids)),
        )
        .order_by(CodeEdge.kind, CodeEdge.line, CodeEdge.id)
        .limit(80)
    ).all()
    related_ids = list(
        dict.fromkeys(
            e.target_symbol_id if e.source_symbol_id in ids else e.source_symbol_id
            for e in edges
        )
    )[:24]
    targets = session.scalars(
        select(CodeSymbol).where(
            CodeSymbol.repo_id == repo_id, CodeSymbol.id.in_(related_ids)
        )
    ).all()
    by_id = {s.id: s for s in targets}
    chunks = (
        session.scalars(
            select(Chunk)
            .where(
                Chunk.repo_id == repo_id,
                Chunk.file_path.in_([s.file_path for s in targets]),
            )
            .order_by(Chunk.file_path, Chunk.start_line)
            .limit(300)
        ).all()
        if targets
        else []
    )
    seen, output = {h.chunk.id for h in seeds}, []
    for symbol_id in related_ids:
        target = by_id.get(symbol_id)
        if not target:
            continue
        matches = [
            c
            for c in chunks
            if c.file_path == target.file_path
            and c.start_line <= target.start_line <= c.end_line
            and c.id not in seen
        ]
        matches.sort(
            key=lambda c: (
                c.symbol_name != target.qualified_name,
                c.end_line - c.start_line,
            )
        )
        if matches:
            chunk = matches[0]
            output.append(
                SearchHit(chunk, "graph_neighbor", channels=("graph_neighbor",))
            )
            seen.add(chunk.id)
        if len(output) >= limit:
            break
    return output


def diverse(hits, top_k):
    selected, deferred, counts = [], [], {}
    for hit in hits:
        path = hit.chunk.file_path
        if counts.get(path, 0) >= 2:
            deferred.append(hit)
        else:
            selected.append(hit)
            counts[path] = counts.get(path, 0) + 1
    return (selected + deferred)[:top_k]


def supporting_source(session, repo_id, seeds, limit=2):
    """Follow retrieved source to enclosing-function tails and referenced definitions.

    All derived windows come from the same immutable source snapshots. Bounded
    support slots prevent long symbol headers from hiding return/error paths,
    and recover configuration definitions through actual attribute references.
    """
    output, seen = [], set()
    for hit in seeds[:3]:
        chunk = hit.chunk
        symbol = session.scalar(
            select(CodeSymbol)
            .where(
                CodeSymbol.repo_id == repo_id,
                CodeSymbol.file_path == chunk.file_path,
                CodeSymbol.start_line <= chunk.start_line,
                CodeSymbol.end_line > chunk.end_line,
                CodeSymbol.kind.in_(["function", "method"]),
            )
            .order_by(CodeSymbol.end_line - CodeSymbol.start_line)
            .limit(1)
        )
        if symbol is None or (symbol.file_path, symbol.end_line) in seen:
            continue
        snapshot = session.get(SourceFile, (repo_id, symbol.file_path))
        if snapshot is None:
            continue
        lines = snapshot.content.splitlines()
        end = min(symbol.end_line, len(lines))
        start, chars = end, 0
        for line in reversed(lines[max(symbol.start_line - 1, end - 40) : end]):
            if chars + len(line) + 1 > 1700:
                break
            chars += len(line) + 1
            start -= 1
        if start >= end:
            continue
        content = "\n".join(lines[start:end])
        derived = Chunk(
            id="source-"
            + hashlib.sha256(
                f"{repo_id}:{symbol.file_path}:{start + 1}:{end}:{content}".encode()
            ).hexdigest()[:28],
            repo_id=repo_id,
            file_path=symbol.file_path,
            symbol_name=symbol.qualified_name,
            kind="source_tail",
            start_line=start + 1,
            end_line=end,
            content=content,
        )
        output.append(SearchHit(derived, "source_tail", channels=("source_tail",)))
        seen.add((symbol.file_path, symbol.end_line))
        if len(output) >= limit:
            return output
    text = "\n".join(h.chunk.content[:2200] for h in seeds[:3])
    bindings = {
        alias or name: module
        for module, name, alias in re.findall(
            r"(?m)^\s*from\s+([\w.]+)\s+import\s+(\w+)(?:\s+as\s+(\w+))?", text
        )
    }
    references = re.findall(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w{3,63})\b", text)
    linked = [(root, attribute) for root, attribute in references if root in bindings]
    identifiers = list(dict.fromkeys(attribute for _, attribute in linked))[:24]
    if identifiers:
        # Identifier fragments are escaped, bounded and passed as SQL values.
        pattern = (
            r"(?m)^\s*(?:(?:export\s+)?(?:const|let|var)\s+)?(?:"
            + "|".join(re.escape(x) for x in identifiers)
            + r")\s*(?::[^=\n]+)?="
        )
        modules = list(
            dict.fromkeys(
                bindings[root].strip(".").replace(".", "/") for root, _ in linked
            )
        )[:8]
        definitions = session.scalars(
            select(Chunk)
            .where(
                Chunk.repo_id == repo_id,
                Chunk.content.op("~")(pattern),
                or_(*[Chunk.file_path.endswith(module + ".py") for module in modules]),
            )
            .order_by(Chunk.file_path, Chunk.start_line)
            .limit(6)
        ).all()
        used = {h.chunk.id for h in output}
        for chunk in definitions:
            if chunk.id not in used:
                linked_hit = next((h for h in seeds if h.chunk.id == chunk.id), None)
                if linked_hit is None:
                    linked_hit = SearchHit(
                        chunk,
                        "reference_definition",
                        channels=("reference_definition",),
                    )
                else:
                    linked_hit.origin = "reference_definition"
                    linked_hit.channels = tuple(
                        dict.fromkeys((*linked_hit.channels, "reference_definition"))
                    )
                output.append(linked_hit)
                used.add(chunk.id)
            if len(output) >= limit:
                break
    return output
