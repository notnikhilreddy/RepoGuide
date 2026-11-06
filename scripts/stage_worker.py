"""Stage only the Python modules needed by each worker role."""

import ast
import json
import shutil
import sys
from pathlib import Path

role = sys.argv[1]
source = Path("/build/src/repoguide")
target = Path("/opt/app/repoguide")
target.mkdir(parents=True)
roots = {
    "answer": ["pipeline", "reranker", "workflow", "evaluation_metrics"],
    "index": ["indexer"],
}
pending = [
    "cloud_state",
    "cloud_product",
    "cloud_bootstrap",
    "db",
    "embeddings",
    *roots[role],
]
if role == "index":
    pending.append("github_api")
selected = {"cloud_worker", "__init__"}
while pending:
    name = pending.pop()
    if name in selected:
        continue
    selected.add(name)
    path = source / (name + ".py")
    for node in ast.walk(ast.parse(path.read_text())):
        imports = []
        if isinstance(node, ast.ImportFrom):
            if node.module == "repoguide":
                imports = [a.name for a in node.names]
            elif node.module and node.module.startswith("repoguide."):
                imports = [node.module.split(".")[1]]
        elif isinstance(node, ast.Import):
            imports = [
                a.name.split(".")[1]
                for a in node.names
                if a.name.startswith("repoguide.")
            ]
        pending.extend(n for n in imports if (source / (n + ".py")).exists())
for name in sorted(selected):
    shutil.copy2(source / (name + ".py"), target)
if role == "answer" and "indexer" in selected:
    raise ValueError("Indexer leaked into Answer worker")
if role == "index" and {"llm", "pipeline", "workflow"} & selected:
    raise ValueError("Answer stack leaked into Index worker")
Path("/opt/app/module-inventory.json").write_text(
    json.dumps(sorted(selected), indent=2)
)
# Development fixtures, headers and bytecode are unnecessary for inference.
site = Path("/opt/venv/lib/python3.12/site-packages")
for path in list(site.rglob("__pycache__")) + list(site.rglob("tests")):
    if path.is_dir():
        shutil.rmtree(path)
for path in [site / "torch/include", site / "torch/share/cmake"]:
    if path.exists():
        shutil.rmtree(path)
