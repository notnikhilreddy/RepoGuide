"""M3: replace broad JS/TS windows with Tree-sitter symbol-boundary chunks.

Python AST symbol chunks from M1 are kept. Small JS/TS module headers still
cover imports/top-level declarations; files without symbols retain all windows.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from repoguide.parser import ParsedChunk, parse_repository, split_lines

JS_SUFFIXES = {".js", ".jsx", ".ts", ".tsx"}


def parse_repository_m3(root: Path, *, analysis) -> list[ParsedChunk]:
    baseline = parse_repository(root)
    by_file: dict[str, list] = defaultdict(list)
    for symbol in analysis.symbols:
        if (
            Path(symbol.file_path).suffix.lower() in JS_SUFFIXES
            and symbol.kind != "module"
        ):
            by_file[symbol.file_path].append(symbol)

    output: list[ParsedChunk] = []
    processed: set[str] = set()
    for chunk in baseline:
        if Path(chunk.file_path).suffix.lower() not in JS_SUFFIXES:
            output.append(chunk)
            continue
        if chunk.file_path in processed:
            continue
        processed.add(chunk.file_path)
        symbols = sorted(by_file.get(chunk.file_path, []), key=lambda x: x.start_line)
        if not symbols:
            # No recognized symbols: keep all original module chunks.
            output.extend(c for c in baseline if c.file_path == chunk.file_path)
            continue

        # Path already vetted by the M1 file collector before we read it.
        text_lines = (
            (root / chunk.file_path)
            .read_text(encoding="utf-8", errors="replace")
            .splitlines()
        )
        # Keep import and top-of-file declarations in one small context window.
        output.extend(
            split_lines(
                text_lines[:45],
                file_path=chunk.file_path,
                symbol_name=None,
                kind="module",
                start_line=1,
            )
        )
        unique = set()
        for symbol in symbols:
            key = (symbol.qualified_name, symbol.start_line, symbol.end_line)
            if key in unique:
                continue
            unique.add(key)
            output.extend(
                split_lines(
                    text_lines[symbol.start_line - 1 : symbol.end_line],
                    file_path=chunk.file_path,
                    symbol_name=symbol.qualified_name,
                    kind=symbol.kind,
                    start_line=symbol.start_line,
                )
            )
    return output
