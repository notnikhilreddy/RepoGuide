import pytest

from evals.benchmark_m3 import quality
from evals.evaluate_answers import check_citations


def test_file_metrics_count_distinct_relevant_files():
    scores = quality(["a.py", "a.py", "b.py", "other.py"], {"a.py", "b.py"}, 4)
    assert scores["hit"] == 1
    assert scores["mrr"] == 1
    assert scores["file_recall"] == 1
    assert 0 < scores["ndcg"] < 1  # second relevant file appears at rank 3


def test_no_relevant_paths():
    scores = quality(["x.py"], {"a.py"}, 4)
    assert scores["hit"] == 0
    assert scores["ndcg"] == 0


def test_unknown_citation_detected():
    result = check_citations("See [S1] and [S7]", [{"label": "S1"}])
    assert result["has_citation"] is True
    assert result["invalid_labels"] == ["[S7]"]
