"""Compare retrieval quality and warm/cold-inclusive latency at a fixed evidence budget.

Example:
 uv run python evals/benchmark_m3.py REPO_ID --data evals/m3_cases.json --top-k 8
"""

import argparse
import json
import math
import statistics
import time
from pathlib import Path

from repoguide.db import SessionLocal
from repoguide.hybrid import search

MODES = (
    "dense",
    "keyword",
    "graph",
    "hybrid",
    "hybrid_graph",
    "hybrid_rerank",
    "hybrid_graph_rerank",
)


def quality(paths: list[str], relevant: set[str], k: int) -> dict:
    paths = paths[:k]
    first = next((i for i, path in enumerate(paths, 1) if path in relevant), None)
    # File-level relevance: duplicate chunks from the same file get no extra gain.
    found = set()
    dcg = 0.0
    for i, path in enumerate(paths, 1):
        if path in relevant and path not in found:
            found.add(path)
            dcg += 1.0 / math.log2(i + 1)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(k, len(relevant)) + 1))
    return {
        "hit": float(first is not None),
        "mrr": 1.0 / first if first else 0.0,
        "file_recall": len(found) / len(relevant),
        "ndcg": dcg / ideal if ideal else 0.0,
    }


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("repo_id")
    p.add_argument("--data", default="evals/retrieval.json")
    p.add_argument("--top-k", type=int, default=8)
    p.add_argument("--candidate-k", type=int, default=32)
    p.add_argument(
        "--modes",
        nargs="+",
        choices=MODES,
        default=["dense", "keyword", "graph", "hybrid", "hybrid_rerank"],
    )
    p.add_argument("--output", default="evals/m3_results.json")
    args = p.parse_args()
    if not 1 <= args.top_k <= 20:
        p.error("--top-k must be 1..20")
    cases = json.loads(Path(args.data).read_text(encoding="utf-8"))
    if not cases:
        raise ValueError("No evaluation examples")
    for case in cases:
        if not case.get("question") or not case.get("expected_paths"):
            raise ValueError(f"Incomplete evaluation case: {case}")

    per_mode: dict[str, list[dict]] = {mode: [] for mode in args.modes}
    with SessionLocal() as session:
        for index, case in enumerate(cases, start=1):
            for mode in args.modes:
                start = time.perf_counter()
                hits = search(
                    session=session,
                    repo_id=args.repo_id,
                    question=case["question"],
                    top_k=args.top_k,
                    candidate_k=args.candidate_k,
                    retrieval_mode=mode,
                )
                latency_ms = (time.perf_counter() - start) * 1000
                paths = [hit.chunk.file_path for hit in hits]
                scores = quality(paths, set(case["expected_paths"]), args.top_k)
                per_mode[mode].append(
                    {
                        "question": case["question"],
                        "latency_ms": latency_ms,
                        "paths": paths,
                        "metrics": scores,
                    }
                )
            print(f"Evaluated {index}/{len(cases)} queries", end="\r", flush=True)
    print()

    aggregate = {}
    header = "mode                      Hit@K   MRR@K  Recall@K  nDCG@K  p50ms  p95ms"
    print(header)
    for mode, records in per_mode.items():
        ms = [r["latency_ms"] for r in records]
        row = {
            metric: statistics.mean(r["metrics"][metric] for r in records)
            for metric in ("hit", "mrr", "file_recall", "ndcg")
        }
        row["p50_ms"] = statistics.median(ms)
        row["p95_ms"] = percentile(ms, 0.95)
        aggregate[mode] = row
        print(
            f"{mode:<25} {row['hit']:>5.3f}   {row['mrr']:>5.3f}  "
            f"{row['file_recall']:>7.3f}   {row['ndcg']:>6.3f}  "
            f"{row['p50_ms']:>5.1f}  {row['p95_ms']:>5.1f}"
        )

    result = {
        "repo_id": args.repo_id,
        "dataset": args.data,
        "top_k": args.top_k,
        "candidate_k": args.candidate_k,
        "query_count": len(cases),
        "aggregate": aggregate,
        "details": per_mode,
        "notes": "Retrieval-only timings; first-use model loads included, not a warmed server benchmark.",
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
