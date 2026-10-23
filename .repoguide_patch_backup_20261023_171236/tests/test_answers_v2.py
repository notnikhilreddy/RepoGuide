import pytest
from repoguide.answers_v2 import parse_draft, validate_draft, abstain


STATE = {"question":"How does indexing work?", "sources":[{"label":"S1", "file_path":"indexer.py"}], "docs_sources":[], "trace": []}


def test_valid_claim():
    raw = '{"status":"answered", "claims":[{"text":"Indexing uses vectors.","citations":["S1"]}],"limitations":[]}'
    final = validate_draft(parse_draft(raw), STATE)
    assert final.status == "answered" and final.verified_labels == ["S1"]
    assert "[S1]" in final.answer


def test_invalid_label_is_not_returned():
    raw = '{"status":"answered", "claims":[{"text":"Invented detail.","citations":["S9"]}],"limitations":[]}'
    final = validate_draft(parse_draft(raw), STATE)
    assert final.status == "insufficient_evidence"
    assert "S9" in final.rejected_labels


def test_mixed_citations_filter_bad_label():
    raw = '{"status":"answered", "claims":[{"text":"A source says something.","citations":["S1","D7"]}],"limitations":[]}'
    final = validate_draft(parse_draft(raw), STATE)
    assert final.verified_labels == ["S1"] and final.rejected_labels == ["D7"]


def test_abstention():
    assert abstain(STATE, "No evidence").status == "insufficient_evidence"


def test_invalid_json():
    with pytest.raises(ValueError):
        parse_draft("not json")
