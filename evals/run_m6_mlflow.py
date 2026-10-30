"""Versioned dataset evaluation. Runs tab = aggregate metrics, Traces tab = spans.

Use --judge only with an explicitly configured MLflow judge model/credentials.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from repoguide.evaluation_metrics import citations_ok, file_recall, hit_at_k, mrr
from repoguide.pipeline import answer
from repoguide.telemetry import setup_mlflow


def load_cases(path: str):
    cases = json.loads(Path(path).read_text())
    if not isinstance(cases, list) or not cases:
        raise ValueError("Evaluation JSON must contain a non-empty list")
    for case in cases:
        if "question" not in case or "expected_paths" not in case:
            raise ValueError("Each case requires question and expected_paths")
    return cases


def run(
    repo_id: str, dataset: str, limit: int | None = None, judge_model: str | None = None
):
    import mlflow

    setup_mlflow()
    cases = load_cases(dataset)[:limit]
    results = []
    ms = []
    with mlflow.start_run(run_name="RepoGuide-M6-evaluation", log_system_metrics=True):
        from repoguide.provider import identity

        model = identity()
        mlflow.log_params(
            {
                "dataset": Path(dataset).name,
                "cases": len(cases),
                "pipeline": "m6",
                "repo_id": repo_id,
                "judge": judge_model or "disabled",
                "provider": model.provider,
                "model": model.model,
                "retrieval_mode": "hybrid",
                "prompt_schema_version": "m6",
            }
        )
        for case in cases:
            start = time.perf_counter()
            response = answer(
                repo_id=repo_id,
                question=case["question"],
                docs_policy=case.get("docs_policy", "never"),
                retrieval_mode=case.get("retrieval_mode", "hybrid"),
                answer_depth="standard",
            )
            elapsed = (time.perf_counter() - start) * 1000
            ms.append(elapsed)
            ranked = [s["file_path"] for s in response.sources]
            expected = case["expected_paths"]
            top_k = 8
            result = {
                "question": case["question"],
                "expected_paths": expected,
                "observed_paths": ranked,
                "hit_at_8": hit_at_k(expected, ranked, top_k),
                "file_recall_at_8": file_recall(expected, ranked, top_k),
                "mrr_at_8": mrr(expected, ranked, top_k),
                "citations_valid": citations_ok(
                    response.answer, response.sources + response.docs_sources
                ),
                "status": response.status,
                "trace_id": response.trace_id,
                "latency_ms": elapsed,
                "answer": response.answer,
            }
            results.append(result)
        for metric in ["hit_at_8", "file_recall_at_8", "mrr_at_8"]:
            mlflow.log_metric(metric, statistics.mean(r[metric] for r in results))
        mlflow.log_metric(
            "citation_label_valid_rate",
            statistics.mean(float(r["citations_valid"]) for r in results),
        )
        mlflow.log_metric(
            "abstention_rate",
            statistics.mean(
                float(r["status"] == "insufficient_evidence") for r in results
            ),
        )
        mlflow.log_metric("latency_p50_ms", statistics.median(ms))
        mlflow.log_metric("latency_max_ms", max(ms))
        mlflow.log_dict(results, "m6/row_results.json")
        if judge_model:
            # Evaluate existing traces (do not generate again). Judge is optional
            # and requires separately configured credentials and provider.
            traces = [mlflow.get_trace(r["trace_id"]) for r in results if r["trace_id"]]
            if traces:
                from mlflow.genai.scorers import (
                    RetrievalGroundedness,
                    RetrievalRelevance,
                )

                mlflow.genai.evaluate(
                    data=traces,
                    scorers=[
                        RetrievalGroundedness(model=judge_model),
                        RetrievalRelevance(model=judge_model),
                    ],
                )
    Path("evals/m6_results.json").write_text(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_id")
    parser.add_argument("--dataset", default="evals/m3_cases.json")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--judge-model", default="")
    opts = parser.parse_args()
    items = run(opts.repo_id, opts.dataset, opts.limit, opts.judge_model or None)
    print(
        json.dumps(
            {"count": len(items), "trace_ids": [r["trace_id"] for r in items]}, indent=2
        )
    )
