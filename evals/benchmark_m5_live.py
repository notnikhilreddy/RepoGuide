"""Optional live quality/latency smoke benchmark (will call LLM and external tools)."""
import json
import sys
import statistics
import time
from pathlib import Path

from repoguide.pipeline import answer as robust_answer

if len(sys.argv) < 3:
    raise SystemExit("Usage: uv run python evals/benchmark_m5_live.py REPO_ID cases.json")
repo_id, path = sys.argv[1:3]
cases = json.loads(Path(path).read_text())
rows = []
for case in cases:
    start = time.perf_counter()
    result = robust_answer(repo_id=repo_id, question=case["question"],
                           docs_policy=case.get("docs_policy", "auto"))
    seconds = round(time.perf_counter() - start, 3)
    row = {
        "question": case["question"],
        "seconds": seconds,
        "status": result.status,
        "citations": result.verified_labels,
        "invalid_citations": result.rejected_labels,
        "cached": result.cached,
        "repo_sources": len(result.sources),
        "docs_sources": result.docs_sources,
        "claims": len(result.claims),
        "limitations": result.limitations,
        "trace": result.trace,
        "manual_correctness": None,
        "manual_faithfulness": None,
    }
    rows.append(row)
    print(row)
Path("evals/m5_live_results.json").write_text(json.dumps(rows, indent=2))
print("Median latency:", statistics.median(row["seconds"] for row in rows))
print("Abstention rate:", sum(r["status"]=="insufficient_evidence" for r in rows)/len(rows))
