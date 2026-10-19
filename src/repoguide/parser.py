import ast
import os

from dataclasses import dataclass
from pathlib import Path


SKIP_DIRECTORIES = {
    ".git", ".venv", "venv", "node_modules",
    "dist", "build", "__pycache__", ".pytest_cache",
}

ALLOWED_SUFFIXES = {
    ".py", ".md", ".rst",
    ".js", ".jsx", ".ts", ".tsx",
}

MAX_FILE_BYTES = 500_000
MAX_REPOSITORY_BYTES = 25_000_000
MAX_FILES = 2_000

MAX_LINES_PER_CHUNK = 60
OVERLAP_LINES = 5


@dataclass
class ParsedChunk:
    file_path: str
    symbol_name: str | None
    kind: str
    start_line: int
    end_line: int
    content: str


def collect_source_files(root: Path) -> list[Path]:
    files = []
    total_bytes = 0

    for directory, dirs, filenames in os.walk(root, followlinks=False):
        dirs[:] = sorted(
            d for d in dirs
            if d not in SKIP_DIRECTORIES
            and not (Path(directory) / d).is_symlink()
        )

        for filename in sorted(filenames):
            path = Path(directory) / filename

            # Never follow symbolic links outside the repository.
            if path.is_symlink() or not path.is_file():
                continue

            if path.suffix.lower() not in ALLOWED_SUFFIXES:
                continue

            size = path.stat().st_size

            if size > MAX_FILE_BYTES:
                continue

            total_bytes += size

            if total_bytes > MAX_REPOSITORY_BYTES:
                raise ValueError("Repository source files exceed size limit")

            files.append(path)

            if len(files) > MAX_FILES:
                raise ValueError("Repository contains too many source files")

    return files


def split_lines(
    lines: list[str],
    *,
    file_path: str,
    symbol_name: str | None,
    kind: str,
    start_line: int,
) -> list[ParsedChunk]:
    chunks = []
    step = MAX_LINES_PER_CHUNK - OVERLAP_LINES

    for offset in range(0, len(lines), step):
        window = lines[offset:offset + MAX_LINES_PER_CHUNK]

        if not window:
            break

        chunk_start = start_line + offset

        chunks.append(
            ParsedChunk(
                file_path=file_path,
                symbol_name=symbol_name,
                kind=kind,
                start_line=chunk_start,
                end_line=chunk_start + len(window) - 1,
                content="\n".join(window),
            )
        )

        if offset + MAX_LINES_PER_CHUNK >= len(lines):
            break

    return chunks


def qualified_name(node: ast.AST, parents: dict) -> str:
    names = [node.name]
    parent = parents.get(node)

    while parent is not None:
        if isinstance(
            parent,
            (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            names.append(parent.name)

        parent = parents.get(parent)

    return ".".join(reversed(names))


def parse_python_file(path: Path, root: Path) -> list[ParsedChunk]:
    source = path.read_text(encoding="utf-8", errors="replace")
    lines = source.splitlines()
    relative_path = path.relative_to(root).as_posix()

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }

    chunks = []

    nodes = sorted(
        (
            node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ),
        key=lambda node: node.lineno,
    )

    for node in nodes:
        symbol = qualified_name(node, parents)

        parent = parents.get(node)
        is_method = False

        while parent is not None:
            if isinstance(parent, ast.ClassDef):
                is_method = True
                break
            parent = parents.get(parent)

        # Include decorators in source lines when present.
        first_line = min(
            [node.lineno] + [
                decorator.lineno for decorator in node.decorator_list
            ]
        )

        symbol_lines = lines[first_line - 1:node.end_lineno]

        chunks.extend(
            split_lines(
                symbol_lines,
                file_path=relative_path,
                symbol_name=symbol,
                kind="method" if is_method else "function",
                start_line=first_line,
            )
        )

    # Include module-level code and declarations as separate
    # context chunks, even when a file contains functions.
    if lines:
        chunks.extend(
            split_lines(
                lines,
                file_path=relative_path,
                symbol_name=None,
                kind="module",
                start_line=1,
            )
        )

    return chunks


def parse_text_file(path: Path, root: Path) -> list[ParsedChunk]:
    text = path.read_text(encoding="utf-8", errors="replace")

    return split_lines(
        text.splitlines(),
        file_path=path.relative_to(root).as_posix(),
        symbol_name=None,
        kind="documentation",
        start_line=1,
    )


def parse_repository(root: Path) -> list[ParsedChunk]:
    chunks = []

    for path in collect_source_files(root):
        if path.suffix.lower() == ".py":
            chunks.extend(parse_python_file(path, root))

        elif path.suffix.lower() in {
            ".md", ".rst", ".js", ".jsx", ".ts", ".tsx"
        }:
            chunks.extend(parse_text_file(path, root))

    return chunks