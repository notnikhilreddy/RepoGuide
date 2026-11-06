"""Run every retrieval mode without any provider/evaluator network calls."""

import json
import os
from pathlib import Path

from sqlalchemy import select

from repoguide.db import SessionLocal
from repoguide.evaluation_metrics import file_recall, hit_at_k, mrr
from repoguide.hybrid import search
from repoguide.models import Repository

if "host.docker.internal" not in os.environ["DATABASE_URL"]:
    raise SystemExit("Only the disposable validation database is allowed")
corpus = json.loads(Path("/evals/release_cases.json").read_text())
results = {}
with SessionLocal() as db:
    repo = db.scalar(
        select(Repository).where(Repository.commit_sha == corpus["fixture"]["commit"])
    )
    for mode in [
        "dense",
        "keyword",
        "graph",
        "hybrid",
        "hybrid_rerank",
        "hybrid_graph",
        "hybrid_graph_rerank",
    ]:
        rows = []
        for case in corpus["cases"]:
            if not case["expected_paths"]:
                continue
            hits = search(
                session=db,
                repo_id=repo.id,
                question=case["question"],
                top_k=8,
                retrieval_mode=mode,
            )
            paths = [h.chunk.file_path for h in hits]
            rows.append(
                {
                    "case": case["id"],
                    "hit": hit_at_k(case["expected_paths"], paths, 8),
                    "mrr": mrr(case["expected_paths"], paths, 8),
                    "recall": file_recall(case["expected_paths"], paths, 8),
                }
            )
        results[mode] = rows
report = {
    "kind": "offline retrieval only",
    "production_gate_evidence": False,
    "live_generation": False,
    "fixture_commit": corpus["fixture"]["commit"],
    "modes": results,
}
Path("/evidence/offline-retrieval.json").write_text(json.dumps(report, indent=2))
print(
    json.dumps(
        {
            "modes": len(results),
            "measured_queries": sum(len(v) for v in results.values()),
            "live_generation": False,
        }
    )
)
