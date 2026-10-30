"""Conservative static analysis. Tree-sitter discovers syntax; it is not a type checker."""

from __future__ import annotations

import ast
import json
import posixpath
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Parser

from repoguide.parser import collect_source_files
from repoguide.telemetry import observed

GRAMMARS = {
    ".py": Language(tree_sitter_python.language()),
    ".js": Language(tree_sitter_javascript.language()),
    ".jsx": Language(tree_sitter_javascript.language()),
    ".ts": Language(tree_sitter_typescript.language_typescript()),
    ".tsx": Language(tree_sitter_typescript.language_tsx()),
}
LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}
SYMBOL_TYPES = {
    "python": {"function_definition": "function", "class_definition": "class"},
    "javascript": {
        "function_declaration": "function",
        "generator_function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "variable_declarator": "function",
    },
    "typescript": {
        "function_declaration": "function",
        "generator_function_declaration": "function",
        "class_declaration": "class",
        "abstract_class_declaration": "class",
        "method_definition": "method",
        "method_signature": "method",
        "interface_declaration": "interface",
        "variable_declarator": "function",
    },
}
CALLEE_RE = re.compile(r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*$")
JS_IMPORT_RE = re.compile(
    r"\bfrom\s*['\"]([^'\"]+)['\"]|\bimport\s*['\"]([^'\"]+)['\"]"
)


@dataclass
class SymbolDraft:
    key: str
    file_path: str
    language: str
    name: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int


@dataclass
class EdgeDraft:
    source_key: str
    kind: str
    target_name: str
    line: int
    target_key: str | None = None


@dataclass
class DependencyDraft:
    name: str
    spec: str
    manifest: str
    group: str = "runtime"


@dataclass
class Analysis:
    symbols: list[SymbolDraft] = field(default_factory=list)
    edges: list[EdgeDraft] = field(default_factory=list)
    dependencies: list[DependencyDraft] = field(default_factory=list)


def module_name(path: str) -> str:
    p = path.removeprefix("src/")
    p = re.sub(r"\.(py|ts|tsx|js|jsx)$", "", p)
    return p.removesuffix("/__init__").replace("/", ".")


def source_text(node, raw: bytes) -> str:
    return raw[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def symbol_key(path: str, qual: str, line: int) -> str:
    return f"{path}::{qual}::{line}"


def last_line(node) -> int:
    # end_point is exclusive; when it is at column zero, the last line is previous.
    return max(
        node.start_point.row + 1,
        node.end_point.row + (1 if node.end_point.column else 0),
    )


def imports_for_python(
    source: str, path: str, module_key: str, result: Analysis, aliases: dict
):
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return

    module = module_name(path)
    package = module if path.endswith("/__init__.py") else module.rpartition(".")[0]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for entry in node.names:
                aliases[(path, entry.asname or entry.name.split(".")[0])] = (
                    entry.name if entry.asname else entry.name.split(".")[0]
                )
                result.edges.append(
                    EdgeDraft(module_key, "imports", entry.name, node.lineno)
                )
        elif isinstance(node, ast.ImportFrom):
            parents = package.split(".") if package else []
            if node.level:
                parents = (
                    parents[: len(parents) - (node.level - 1)]
                    if node.level <= len(parents) + 1
                    else []
                )
                prefix = ".".join(parents)
                target_module = ".".join(
                    part for part in (prefix, node.module or "") if part
                )
            else:
                target_module = node.module or ""
            result.edges.append(
                EdgeDraft(module_key, "imports", target_module or ".", node.lineno)
            )
            for entry in node.names:
                if entry.name != "*":
                    aliases[(path, entry.asname or entry.name)] = ".".join(
                        x for x in (target_module, entry.name) if x
                    )


def resolve_js_path(current_path: str, spec: str, paths: set[str]) -> str | None:
    if not spec.startswith("."):
        return None
    base = posixpath.normpath(posixpath.join(posixpath.dirname(current_path), spec))
    for candidate in [
        base,
        *(f"{base}{ext}" for ext in (".js", ".jsx", ".ts", ".tsx")),
        *(f"{base}/index{ext}" for ext in (".js", ".jsx", ".ts", ".tsx")),
    ]:
        if candidate in paths:
            return candidate
    return None


def scan_file(
    root: Path, path: Path, result: Analysis, aliases: dict, imported_js: dict
):
    rel = path.relative_to(root).as_posix()
    lang = LANGUAGES[path.suffix.lower()]
    raw = path.read_bytes()
    source = raw.decode("utf-8", errors="replace")
    tree = Parser(GRAMMARS[path.suffix.lower()]).parse(raw)
    if tree is None:
        return

    n_lines = max(len(source.splitlines()), 1)
    module = module_name(rel)
    module_key = symbol_key(rel, module, 1)
    result.symbols.append(
        SymbolDraft(module_key, rel, lang, module, module, "module", 1, n_lines)
    )

    def walk(node, parent: SymbolDraft):
        kind = SYMBOL_TYPES[lang].get(node.type)
        current = parent
        if kind:
            # For JS/TS we index arrow functions bound to named variables.
            if node.type == "variable_declarator":
                value = node.child_by_field_name("value")
                if value is None or value.type not in {
                    "arrow_function",
                    "function_expression",
                    "function",
                }:
                    kind = None
            name_node = node.child_by_field_name("name") if kind else None
            if name_node is not None:
                name = source_text(name_node, raw)
                if CALLEE_RE.fullmatch(name):
                    if parent.kind == "module":
                        qual = name
                    else:
                        # Construct the lexical path inside the file, not including module.
                        parent_local = parent.qualified_name
                        if parent_local.startswith(module + "."):
                            parent_local = parent_local[len(module) + 1 :]
                        qual = f"{parent_local}.{name}"
                    if parent.kind == "class" and kind == "function":
                        kind = "method"
                    key = symbol_key(rel, qual, node.start_point.row + 1)
                    current = SymbolDraft(
                        key,
                        rel,
                        lang,
                        name,
                        qual,
                        kind,
                        node.start_point.row + 1,
                        last_line(node),
                    )
                    result.symbols.append(current)
                    result.edges.append(
                        EdgeDraft(parent.key, "contains", qual, current.start_line, key)
                    )

        if node.type in ({"call"} if lang == "python" else {"call_expression"}):
            callee_node = node.child_by_field_name("function")
            if callee_node is not None:
                target = source_text(callee_node, raw)
                if len(target) <= 150 and CALLEE_RE.fullmatch(target):
                    result.edges.append(
                        EdgeDraft(
                            current.key, "calls", target, node.start_point.row + 1
                        )
                    )

        if lang != "python" and node.type == "import_statement":
            statement = source_text(node, raw)
            match = JS_IMPORT_RE.search(statement)
            if match:
                spec = match.group(1) or match.group(2)
                result.edges.append(
                    EdgeDraft(module_key, "imports", spec, node.start_point.row + 1)
                )
                # Parse a conservative subset of named imports and default imports.
                before_from = (
                    statement.split(" from ")[0].removeprefix("import ").strip()
                )
                mapping = {}
                braces = re.search(r"\{([^}]+)\}", before_from)
                if braces:
                    for item in braces.group(1).split(","):
                        words = item.strip().split(" as ")
                        if len(words) in (1, 2) and all(
                            re.fullmatch(r"[\w$]+", w.strip()) for w in words
                        ):
                            mapping[words[-1].strip()] = words[0].strip()
                else:
                    default = before_from.split(",")[0].strip()
                    if re.fullmatch(r"[\w$]+", default):
                        mapping[default] = "default"
                for local, imported in mapping.items():
                    imported_js[(rel, local)] = (spec, imported)

        for child in node.named_children:
            walk(child, current)

    walk(tree.root_node, result.symbols[-1])
    if lang == "python":
        imports_for_python(source, rel, module_key, result, aliases)


def resolve_edges(result: Analysis, aliases: dict, imported_js: dict):
    by_key = {symbol.key: symbol for symbol in result.symbols}
    by_file_name: dict[tuple[str, str], list[SymbolDraft]] = {}
    by_global_name: dict[str, list[SymbolDraft]] = {}
    module_by_name = {}
    module_by_path = {}
    for s in result.symbols:
        by_file_name.setdefault((s.file_path, s.qualified_name), []).append(s)
        if s.kind == "module":
            module_by_name[s.qualified_name] = s
            module_by_path[s.file_path] = s
        elif s.language == "python":
            full = f"{module_name(s.file_path)}.{s.qualified_name}"
            by_global_name.setdefault(full, []).append(s)

    paths = set(module_by_path)

    def only(seq):
        return seq[0] if len(seq) == 1 else None

    for edge in result.edges:
        if edge.target_key is not None:
            continue
        caller = by_key[edge.source_key]
        if edge.kind == "imports":
            if caller.language == "python":
                target = module_by_name.get(edge.target_name)
            else:
                p = resolve_js_path(caller.file_path, edge.target_name, paths)
                target = module_by_path.get(p) if p else None
            if target:
                edge.target_key = target.key
            continue
        if edge.kind != "calls":
            continue
        callee = edge.target_name
        target = None
        if callee.startswith(("self.", "cls.", "this.")) and caller.kind == "method":
            class_qual = caller.qualified_name.rpartition(".")[0]
            target = only(
                by_file_name.get(
                    (caller.file_path, f"{class_qual}.{callee.split('.', 1)[1]}"), []
                )
            )
        if target is None:
            target = only(by_file_name.get((caller.file_path, callee), []))
        if target is None and caller.language == "python":
            alias, _, suffix = callee.partition(".")
            mapped = aliases.get((caller.file_path, alias))
            full = f"{mapped}.{suffix}" if mapped and suffix else mapped
            if full:
                target = only(by_global_name.get(full, []))
            if target is None:
                target = only(by_global_name.get(callee, []))
        if target is None and caller.language != "python":
            alias, _, _ = callee.partition(".")
            entry = imported_js.get((caller.file_path, alias))
            if entry and "." not in callee:
                path = resolve_js_path(caller.file_path, entry[0], paths)
                if path:
                    candidates = [
                        s
                        for s in by_file_name.get((path, entry[1]), [])
                        if s.kind != "module"
                    ]
                    target = only(candidates)
        if target and target.kind != "module":
            edge.target_key = target.key


def dependencies_from_manifests(root: Path) -> list[DependencyDraft]:
    result = []
    p = root / "pyproject.toml"
    if p.is_file() and not p.is_symlink() and p.stat().st_size < 500_000:
        doc = tomllib.loads(p.read_text(encoding="utf-8"))
        for group, values in [
            ("runtime", doc.get("project", {}).get("dependencies", [])),
            *doc.get("project", {}).get("optional-dependencies", {}).items(),
            *doc.get("dependency-groups", {}).items(),
        ]:
            for value in values:
                name = re.split(r"[<=>~!;\[\s]", value, 1)[0]
                if name:
                    result.append(DependencyDraft(name, value, "pyproject.toml", group))
    p = root / "requirements.txt"
    if p.is_file() and not p.is_symlink() and p.stat().st_size < 500_000:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "-", "git+")):
                name = re.split(r"[<=>~!;\[\s]", line, 1)[0]
                if name:
                    result.append(DependencyDraft(name, line, "requirements.txt"))
    p = root / "package.json"
    if p.is_file() and not p.is_symlink() and p.stat().st_size < 500_000:
        doc = json.loads(p.read_text(encoding="utf-8"))
        for field, group in (
            ("dependencies", "runtime"),
            ("devDependencies", "dev"),
            ("peerDependencies", "peer"),
        ):
            for name, spec in doc.get(field, {}).items():
                result.append(DependencyDraft(name, spec, "package.json", group))
    return result


@observed("index.analyze_symbols", "CHAIN")
def analyze_repository(root: Path) -> Analysis:
    result = Analysis()
    aliases = {}
    imported_js = {}
    for path in collect_source_files(root):
        if path.suffix.lower() in GRAMMARS:
            scan_file(root, path, result, aliases, imported_js)
    resolve_edges(result, aliases, imported_js)
    result.dependencies = dependencies_from_manifests(root)
    return result
