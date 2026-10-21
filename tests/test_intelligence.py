from pathlib import Path

from repoguide.intelligence import analyze_repository


def test_python_cross_file_resolution(tmp_path: Path):
    pkg = tmp_path / "src" / "demo"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "auth.py").write_text(
        "from demo.db import find_user\n\n"
        "def login(name):\n"
        "    return find_user(name)\n",
        encoding="utf-8",
    )
    (pkg / "db.py").write_text(
        "def find_user(name):\n    return name\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="demo"\nversion="0.1.0"\n'
        'dependencies=["fastapi>=0.100", "httpx"]\n',
        encoding="utf-8",
    )

    analysis = analyze_repository(tmp_path)
    by_key = {s.key: s for s in analysis.symbols}

    links = [
        e for e in analysis.edges if e.kind == "calls" and e.target_name == "find_user"
    ]
    assert len(links) == 1
    assert links[0].target_key is not None
    assert by_key[links[0].target_key].qualified_name == "find_user"
    assert by_key[links[0].target_key].file_path == "src/demo/db.py"
    assert any(e.kind == "imports" for e in analysis.edges)
    assert {d.name for d in analysis.dependencies} == {"fastapi", "httpx"}


def test_unresolved_call_remains_unresolved(tmp_path: Path):
    f = tmp_path / "main.py"
    f.write_text("def main():\n    unknown_dynamic_call()\n", encoding="utf-8")
    analysis = analyze_repository(tmp_path)
    matching = [
        e
        for e in analysis.edges
        if e.kind == "calls" and e.target_name == "unknown_dynamic_call"
    ]
    assert len(matching) == 1
    assert matching[0].target_key is None


def test_typescript_and_js_symbols(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "helper.ts").write_text(
        "export function helper() { return 1; }\n", encoding="utf-8"
    )
    (src / "index.ts").write_text(
        'import { helper } from "./helper";\nfunction main() { return helper(); }\n',
        encoding="utf-8",
    )
    (src / "ui.js").write_text(
        "class Widget { render() { return 1; } }\n", encoding="utf-8"
    )
    analysis = analyze_repository(tmp_path)
    symbols = {(s.file_path, s.qualified_name) for s in analysis.symbols}
    assert ("src/helper.ts", "helper") in symbols
    assert ("src/index.ts", "main") in symbols
    assert ("src/ui.js", "Widget.render") in symbols
    calls = [
        e for e in analysis.edges if e.kind == "calls" and e.target_name == "helper"
    ]
    assert len(calls) == 1
    assert calls[0].target_key is not None


def test_class_method_and_self_call(tmp_path: Path):
    (tmp_path / "example.py").write_text(
        "class Service:\n"
        "    def work(self):\n"
        "        return self.helper()\n"
        "    def helper(self):\n"
        "        return 1\n",
        encoding="utf-8",
    )
    result = analyze_repository(tmp_path)
    graph = {s.key: s for s in result.symbols}
    calls = [
        e for e in result.edges if e.kind == "calls" and e.target_name == "self.helper"
    ]
    assert len(calls) == 1
    assert calls[0].target_key is not None
    assert graph[calls[0].target_key].qualified_name == "Service.helper"
