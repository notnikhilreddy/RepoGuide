"""Strict release comparator. Missing, stale, invalid or worse evidence blocks."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HIGHER = {
    "hit",
    "mrr",
    "file_recall",
    "ndcg",
    "routing_intent_accuracy",
    "tool_precision",
    "tool_recall",
    "docs_needed_recall",
    "grounding",
    "correctness",
    "fact_coverage",
    "relevance",
    "citation_precision",
    "citation_coverage",
    "supported_claim_precision",
    "abstention_accuracy",
    "answer_success",
}
LOWER = {
    "unnecessary_tool_rate",
    "tool_timeout_rate",
    "tool_error_rate",
    "unsupported_claim_rate",
    "false_answer_rate",
    "false_abstain_rate",
    "error_rate",
}
SAFETY = {
    "no_secret_leak",
    "no_forbidden_tool",
    "schema_valid",
    "embedding_384",
    "source_provenance",
    "cache_bypassed",
    "malformed_input",
    "injection_resistance",
}
REQUIRED_METADATA = {
    "dataset_sha256",
    "fixture_commit",
    "scorer_version",
    "judge_model",
    "hardware",
    "dependency_sha256",
    "top_k",
    "embedding_revision",
}


def validate(report):
    if report.get("complete") is not True or report.get("live_generation") is not True:
        raise ValueError("Evaluation incomplete or no live generation/judge evidence")
    if (
        report.get("cache_hits") != 0
        or not report.get("case_ids")
        or len(set(report["case_ids"])) != len(report["case_ids"])
    ):
        raise ValueError("Empty/duplicate cases or cached evaluation")
    if not REQUIRED_METADATA.issubset(report.get("metadata", {})):
        raise ValueError("Missing evaluation metadata")
    if (
        not report.get("source_sha256")
        or not report.get("image_id")
        or not report.get("release_config_sha256")
    ):
        raise ValueError("Missing immutable source/image identity")
    if not re.fullmatch("[0-9a-f]{64}", report["source_sha256"]) or not re.fullmatch(
        "sha256:[0-9a-f]{64}", report["image_id"]
    ):
        raise ValueError("Invalid immutable artifact identity")
    if not isinstance(report["case_ids"], list) or report["metadata"]["top_k"] != 8:
        raise ValueError("Invalid case set or retrieval budget")
    timestamp = datetime.fromisoformat(report["created_at"].replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - timestamp).total_seconds()
    if age < -300 or age > 7 * 86400:
        raise ValueError("Stale or future evaluation")
    if not SAFETY.issubset(report.get("safety", {})) or any(
        report["safety"][s] is not True for s in SAFETY
    ):
        raise ValueError("Mandatory safety gate failed or absent")
    if (
        type(report.get("generation_requests")) is not int
        or report["generation_requests"] < 1
    ):
        raise ValueError("No successful live answer generation was measured")
    if type(report.get("repeats")) is not int or report["repeats"] < 2:
        raise ValueError("Repeated paired measurements are required")
    if not report.get("ranges"):
        raise ValueError("Missing measurement ranges; comparison is inconclusive")
    metrics = report.get("metrics", {})
    for metric in HIGHER | LOWER:
        if metric not in metrics:
            raise ValueError("Missing mandatory metric: " + metric)
    if not report.get("slices") or not report.get("retrieval_modes"):
        raise ValueError("Missing protected slice or retrieval-mode results")
    for group in [
        metrics,
        *report["slices"].values(),
        *report["retrieval_modes"].values(),
    ]:
        if not group:
            raise ValueError("Empty metric group")
        for key, value in group.items():
            if (
                key not in HIGHER | LOWER
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                raise ValueError("Invalid metric schema/value: " + key)
    perf = report.get("performance", {})
    for key, ceiling in [
        ("warm_p95_seconds", 180),
        ("tokens_per_answer", 20000),
        ("external_calls_per_answer", 8),
    ]:
        value = perf.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= ceiling
        ):
            raise ValueError("Performance/cost ceiling missing or exceeded: " + key)


def compare(baseline, candidate):
    validate(baseline)
    validate(candidate)
    if baseline["case_ids"] != candidate["case_ids"]:
        raise ValueError("Corpus mismatch")
    for key in REQUIRED_METADATA - {"dependency_sha256"}:
        if baseline["metadata"][key] != candidate["metadata"][key]:
            raise ValueError("Non-comparable evaluation: " + key)
    if candidate.get("tool_probe", {}).get("context7", {}).get("success") is not True:
        raise ValueError("Enabled Context7 tool did not pass its live probe")
    regressions = []
    inconclusive = []
    for category in ["metrics", "slices", "retrieval_modes"]:
        left, right = baseline[category], candidate[category]
        if left.keys() != right.keys():
            raise ValueError("Metric/slice schema mismatch")
        groups = (
            [("all", left, right)]
            if category == "metrics"
            else [(key, left[key], right[key]) for key in left]
        )
        for group, before, after in groups:
            if before.keys() != after.keys():
                raise ValueError("Protected metric schema mismatch")
            for name, value in before.items():
                range_key = category + "/" + group + "/" + name
                bounds = []
                for report, average_value in [
                    (baseline, value),
                    (candidate, after[name]),
                ]:
                    interval = report["ranges"].get(range_key, {})
                    low, high = interval.get("min"), interval.get("max")
                    if (
                        any(
                            isinstance(v, bool)
                            or not isinstance(v, (int, float))
                            or not math.isfinite(v)
                            for v in [low, high]
                        )
                        or not 0 <= low <= average_value <= high <= 1
                    ):
                        raise ValueError(
                            "Missing/invalid measured interval: " + range_key
                        )
                    bounds.append((low, high))
                if (name in HIGHER and bounds[1][0] < bounds[0][1]) or (
                    name in LOWER and bounds[1][1] > bounds[0][0]
                ):
                    inconclusive.append(
                        {
                            "metric": range_key,
                            "baseline_range": bounds[0],
                            "candidate_range": bounds[1],
                        }
                    )
                if (name in HIGHER and after[name] < value) or (
                    name in LOWER and after[name] > value
                ):
                    regressions.append(
                        {
                            "group": category + "/" + group,
                            "metric": name,
                            "baseline": value,
                            "candidate": after[name],
                        }
                    )
    return {
        "passed": not regressions and not inconclusive,
        "inconclusive": inconclusive,
        "regressions": regressions,
        "baseline_source": baseline["source_sha256"],
        "candidate_source": candidate["source_sha256"],
        "candidate_image": candidate["image_id"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline")
    parser.add_argument("candidate")
    parser.add_argument("--output", default=".artifacts/quality-comparison.json")
    args = parser.parse_args()
    try:
        result = compare(
            json.loads(Path(args.baseline).read_text()),
            json.loads(Path(args.candidate).read_text()),
        )
    except Exception as exc:
        result = {"passed": False, "blocker": str(exc)}
    Path(args.output).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
