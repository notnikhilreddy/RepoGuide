"""Publication projects measured public-fixture results, never inventing missing runs."""

import copy

import pytest

from scripts.seed_cloud_catalog import public_report


def measured():
    case = {
        "id": "fixture",
        "question": "Where is the entry point?",
        "expected_paths": ["src/main.py"],
    }
    row = {
        "id": "fixture",
        "repetition": 0,
        "latency_seconds": 1.25,
        "answer": {
            "answer": "The entry point [S1].",
            "sources": [{"file_path": "src/main.py"}],
            "trace_id": "trace-fixture",
        },
    }
    report = {
        "complete": True,
        "live_generation": True,
        "case_ids": ["fixture"],
        "cases": [row, {**copy.deepcopy(row), "repetition": 1}],
        "repeats": 2,
        "retrieval_modes": {"hybrid": {"hit": 1, "mrr": 1, "file_recall": 1}},
        "metrics": {"correctness": 0.875},
        "performance": {"warm_p95_seconds": 1.25},
        "source_sha256": "a" * 64,
        "metadata": {
            "fixture_commit": "b" * 40,
            "hardware": "offline protocol fixture",
        },
        "image_id": "private image identity",
        "owner_sub": "must-not-export",
    }
    return report, {"cases": [case]}


def test_export_keeps_actual_scores_and_selected_paths_without_private_infrastructure():
    report, corpus = measured()
    exported = public_report("measured.json", report, corpus)
    assert exported["quality_metrics"] == report["metrics"]
    assert len(exported["results"]) == 2
    assert exported["results"][0]["hit_at_8"] == 1
    assert exported["results"][0]["latency_ms"] == 1250
    assert exported["results"][0]["observed_paths"] == ["src/main.py"]
    assert "image_id" not in exported and "owner_sub" not in exported


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(complete=False),
        lambda r: r.update(live_generation=False),
        lambda r: r["cases"].pop(),
    ],
)
def test_export_rejects_unmeasured_or_partial_results(mutation):
    report, corpus = measured()
    mutation(report)
    with pytest.raises(ValueError):
        public_report("invalid.json", report, corpus)
