import copy
import hashlib
import json
from datetime import datetime, timezone

import pytest

from evals.product_release_policy import measured_comparison
from evals.release_gate import HIGHER, LOWER, REQUIRED_METADATA, SAFETY, compare


def valid():
    report = {
        "complete": True,
        "live_generation": True,
        "cache_hits": 0,
        "case_ids": ["a"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": "a" * 64,
        "release_config_sha256": "c" * 64,
        "image_id": "sha256:" + "b" * 64,
        "metadata": {k: "value" for k in REQUIRED_METADATA},
        "safety": {k: True for k in SAFETY},
        "metrics": {**dict.fromkeys(HIGHER, 0.8), **dict.fromkeys(LOWER, 0.1)},
        "slices": {"security": {"grounding": 1}},
        "retrieval_modes": {"dense": {"hit": 1}},
        "performance": {
            "warm_p95_seconds": 15,
            "tokens_per_answer": 1000,
            "external_calls_per_answer": 2,
        },
    }

    report["metadata"]["top_k"] = 8
    report["generation_requests"] = 2
    report["repeats"] = 2
    report["tool_probe"] = {"context7": {"success": True}}
    report["ranges"] = {}
    for category in ["metrics", "slices", "retrieval_modes"]:
        groups = (
            {"all": report[category]} if category == "metrics" else report[category]
        )
        for group, metrics in groups.items():
            for metric, value in metrics.items():
                report["ranges"][category + "/" + group + "/" + metric] = {
                    "min": value,
                    "max": value,
                }
    return report


def test_equal_and_better_pass():
    baseline = valid()
    candidate = copy.deepcopy(baseline)
    assert compare(baseline, candidate)["passed"]
    candidate["metrics"]["grounding"] = 0.9
    candidate["ranges"]["metrics/all/grounding"] = {"min": 0.9, "max": 0.9}
    assert compare(baseline, candidate)["passed"]


@pytest.mark.parametrize("key", sorted(HIGHER | LOWER))
def test_each_worse_metric_blocks_without_rounding(key):
    baseline, candidate = valid(), valid()
    candidate["metrics"][key] += -1e-12 if key in HIGHER else 1e-12
    value = candidate["metrics"][key]
    candidate["ranges"]["metrics/all/" + key] = {"min": value, "max": value}
    assert not compare(baseline, candidate)["passed"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(complete=False),
        lambda r: r.update(live_generation=False),
        lambda r: r.update(case_ids=[]),
        lambda r: r.update(cache_hits=1),
        lambda r: r["metrics"].update(grounding=float("nan")),
        lambda r: r["metrics"].pop("grounding"),
        lambda r: r["safety"].update(no_secret_leak=False),
        lambda r: r["metadata"].update(judge_model="different"),
        lambda r: r.update(created_at="2000-01-01T00:00:00Z"),
        lambda r: r.update(slices={}),
        lambda r: r["performance"].update(tokens_per_answer=100000),
    ],
)
def test_missing_inconclusive_unsafe_or_incompatible_fails_closed(mutation):
    baseline, candidate = valid(), valid()
    mutation(candidate)
    with pytest.raises(ValueError):
        compare(baseline, candidate)
    assert baseline == valid() | {"created_at": baseline["created_at"]}


def test_stochastic_overlap_fails_closed_even_when_means_match():
    baseline, candidate = valid(), valid()
    for report in [baseline, candidate]:
        report["ranges"]["metrics/all/grounding"] = {"min": 0.7, "max": 0.9}
    assert not compare(baseline, candidate)["passed"]


def test_target_dependency_changes_are_recorded_and_evaluated():
    baseline, candidate = valid(), valid()
    candidate["metadata"]["dependency_sha256"] = "new evaluated lock"
    assert compare(baseline, candidate)["passed"]


def reviewed_tradeoff():
    baseline, candidate = valid(), valid()
    baseline["slices"]["grounding"] = {"citation_precision": 1.0}
    candidate["slices"]["grounding"] = {"citation_precision": 0.875}
    baseline["ranges"]["slices/grounding/citation_precision"] = {"min": 1, "max": 1}
    candidate["ranges"]["slices/grounding/citation_precision"] = {"min": 0.75, "max": 1}
    result = compare(baseline, candidate)
    policy = {
        "version": "product-owner-tradeoffs-v1",
        "source_sha256": candidate["source_sha256"],
        "baseline_source_sha256": baseline["source_sha256"],
        "candidate_report_sha256": hashlib.sha256(
            json.dumps(candidate, sort_keys=True).encode()
        ).hexdigest(),
        "accept_overlapping_observed_ranges": True,
        "accepted_slice_regressions": result["regressions"],
        "authorization": {
            "instruction": "Publish the measured explanatory answer candidate"
        },
    }
    return baseline, candidate, policy


def test_explicit_review_preserves_strict_rejection_and_measured_tradeoffs():
    baseline, candidate, policy = reviewed_tradeoff()
    assert not measured_comparison(baseline, candidate)["passed"]
    accepted = measured_comparison(baseline, candidate, policy)
    assert accepted["passed"] and accepted["strict_non_regression_passed"] is False
    assert accepted["regressions"] == compare(baseline, candidate)["regressions"]
    assert accepted["inconclusive"]


def test_review_cannot_authorize_changed_source_or_measurement():
    baseline, candidate, policy = reviewed_tradeoff()
    candidate["source_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="exact release"):
        measured_comparison(baseline, candidate, policy)


def test_review_cannot_authorize_an_additional_global_regression():
    baseline, candidate, policy = reviewed_tradeoff()
    candidate["metrics"]["correctness"] = 0.7
    candidate["ranges"]["metrics/all/correctness"] = {"min": 0.7, "max": 0.7}
    policy["candidate_report_sha256"] = hashlib.sha256(
        json.dumps(candidate, sort_keys=True).encode()
    ).hexdigest()
    with pytest.raises(ValueError, match="Unreviewed"):
        measured_comparison(baseline, candidate, policy)


def test_review_cannot_bypass_safety_or_missing_measurements():
    baseline, candidate, policy = reviewed_tradeoff()
    candidate["safety"]["no_secret_leak"] = False
    with pytest.raises(ValueError, match="safety"):
        measured_comparison(baseline, candidate, policy)
