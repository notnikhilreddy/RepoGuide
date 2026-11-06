"""Upstream routing failures must not turn a grounded answer into a failed job."""

import json

import pytest

from repoguide import router
from repoguide.answers import DraftAnswer, prompt_for_evidence, validate_draft


@pytest.mark.parametrize("provider", ["jev", "llm"])
@pytest.mark.parametrize("policy", ["auto", "always"])
def test_both_router_services_malformed_json_degrades_safely(
    monkeypatch, provider, policy
):
    monkeypatch.setattr(router.settings, "router_provider", provider)
    attempts = []

    def broken_jev(*args):
        attempts.append("jev")
        raise json.JSONDecodeError("bad upstream response", "", 0)

    def broken_llm(*args):
        attempts.append("llm")
        raise json.JSONDecodeError("bad fallback response", "", 0)

    monkeypatch.setattr(router, "_jev_route", broken_jev)
    monkeypatch.setattr(router, "_llm_route", broken_llm)
    result = router.decide(
        "Explain SQLAlchemy rollback", [], ["alembic", "sqlalchemy"], policy
    )
    assert result.router == "fallback"
    assert result.sufficient is False
    assert attempts == (["jev", "llm"] if provider == "jev" else ["llm"])
    assert result.tools == (["context7"] if policy == "always" else [])
    assert result.dependencies == (["sqlalchemy"] if policy == "always" else [])


def test_router_outage_forces_truthful_partial_even_if_model_claims_complete():
    state = {
        "question": "Explain rollback",
        "repo_context": "[S1] The session rolls back on exceptions.",
        "sources": [{"label": "S1"}],
        "routing": {"router": "fallback", "tools": []},
    }
    assert "Evidence routing is unavailable" in prompt_for_evidence(state)
    result = validate_draft(
        DraftAnswer(
            status="answered",
            answer="The session rolls back [S1].",
            claims=[],
            limitations=[],
        ),
        state,
    )
    assert result.status == "partial"
    assert result.verified_labels == ["S1"]
    assert "routing unavailable" in result.limitations[-1]
