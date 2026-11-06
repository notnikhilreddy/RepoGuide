"""Regression cases for evidence coverage, context isolation and spend limits."""

import json
from types import SimpleNamespace

import pytest

from evals.cost_budget import SpendingLedger
from repoguide import github_api
from repoguide.chunking import parse_repository_m3
from repoguide.parser import collect_source_files, parse_repository
from repoguide.retrieval_context import bounded_history, retrieval_question


def test_manifests_and_configuration_are_searchable_with_original_lines(tmp_path):
    (tmp_path / "package.json").write_text('{\n  "dependencies": {"react": "19"}\n}\n')
    (tmp_path / "infra.tf").write_text(
        'resource "example" "worker" {\n  count = 0\n}\n'
    )
    (tmp_path / ".env").write_text("PRIVATE_VALUE=do-not-index")
    diagnostics = {}
    files = collect_source_files(tmp_path, diagnostics=diagnostics)
    assert {p.name for p in files} == {"package.json", "infra.tf"}
    chunks = parse_repository(tmp_path)
    assert {c.file_path for c in chunks} == {"package.json", "infra.tf"}
    assert all(c.start_line == 1 and c.end_line == 3 for c in chunks)
    assert diagnostics["excluded_file_count"] == 1
    assert diagnostics["excluded_files"][0]["path"] == ".env"


def test_javascript_late_top_level_registration_is_not_lost(tmp_path):
    (tmp_path / "worker.ts").write_text(
        "\n".join(
            ["// header"] * 50
            + ["export function run() {", "  return 1;", "}"]
            + ["// gap"] * 10
            + ["registerWorker(run);"]
        )
        + "\n"
    )
    symbol = SimpleNamespace(
        file_path="worker.ts",
        kind="function",
        start_line=51,
        end_line=53,
        qualified_name="run",
    )
    chunks = parse_repository_m3(tmp_path, analysis=SimpleNamespace(symbols=[symbol]))
    assert any(
        "registerWorker(run)" in c.content and c.start_line <= 64 <= c.end_line
        for c in chunks
    )
    assert any(c.symbol_name == "run" for c in chunks)


def test_followup_context_is_bounded_without_turning_previous_prose_into_query():
    history = [
        {"role": "user", "content": "Explain file reconstruction", "paths": []},
        {
            "role": "assistant",
            "content": "PRIVATE_UNTRUSTED_PROSE",
            "paths": ["src/source_store.py"],
        },
    ]
    bounded = bounded_history(history)
    query = retrieval_question("Can that look complete?", bounded, {})
    assert "src/source_store.py" in query and "file reconstruction" in query
    assert "PRIVATE_UNTRUSTED_PROSE" not in query
    large = bounded_history(
        [{"role": "assistant", "content": "x" * 9000, "paths": ["a.py"]}] * 100
    )
    assert len(large) <= 6 and len(json.dumps(large)) <= 4500


def test_spend_is_reserved_across_instances_before_any_request(tmp_path):
    first = SpendingLedger(tmp_path / "spend.json")
    request = {
        "model": "gpt-6-luna",
        "service_tier": "default",
        "input": "source evidence",
        "max_output_tokens": 2000,
    }
    first.reserve(request)
    second = SpendingLedger(tmp_path / "spend.json")
    with second.locked() as value:
        assert value["reserved_micros"] > 0
        value["ceiling_micros"] = value["reserved_micros"]
    with pytest.raises(RuntimeError, match="budget"):
        second.reserve(request)
    with second.locked() as value:
        assert (
            len(value["requests"]) == 1 and value["requests"][0]["status"] == "reserved"
        )


def test_unknown_model_or_tier_cannot_bypass_verified_pricing(tmp_path):
    budget = SpendingLedger(tmp_path / "spend.json")
    for request in [
        {"model": "unknown", "max_output_tokens": 10},
        {"model": "gpt-6-luna", "service_tier": "priority", "max_output_tokens": 10},
    ]:
        with pytest.raises(ValueError, match="price"):
            budget.reserve(request)
    assert not (tmp_path / "spend.json").exists()


def test_public_index_pins_commit_and_rejects_large_or_private_repos(monkeypatch):
    metadata = {
        "private": False,
        "size": 20,
        "default_branch": "main",
        "full_name": "sample/repo",
    }
    calls = []

    def request(path, **kwargs):
        calls.append(path)
        return (
            metadata
            if path == "/repos/sample/repo"
            else {"sha": "b" * 40, "commit": {"message": "Fix routing\nDetails"}}
        ), {}

    monkeypatch.setattr(github_api, "request", request)
    result = github_api.prepare_index({"url": "https://github.com/sample/repo"})
    assert result["commit_sha"] == "b" * 40 and result["branch"] == "main"
    assert result["commit_message"] == "Fix routing" and result["private"] is False
    metadata["private"] = True
    with pytest.raises(ValueError, match="public"):
        github_api.prepare_index({"url": "https://github.com/sample/repo"})
    metadata.update(private=False, size=100000)
    with pytest.raises(ValueError, match="50 MiB"):
        github_api.prepare_index({"url": "https://github.com/sample/repo"})


def test_freshness_failure_is_distinct_from_unchanged(monkeypatch):
    repo = {"id": "id", "url": "https://github.com/sample/repo", "commit_sha": "a" * 40}
    grant = {
        "pk": "repository#id",
        "monitored_branch": "main",
        "branch_explicit": True,
        "checked_at": 0,
        "remote_sha": "a" * 40,
        "freshness_status": "up_to_date",
    }
    writes = []
    monkeypatch.setattr(
        github_api.state, "update", lambda *args, **kw: writes.append((args, kw))
    )
    monkeypatch.setattr(
        github_api,
        "request",
        lambda *a, **kw: (_ for _ in ()).throw(github_api.GitHubError(429, 9999)),
    )
    result = github_api.check_update(repo, grant, "user")
    assert result["freshness_status"] == "error" and "limit" in result["check_error"]
    assert result["remote_sha"] == "a" * 40
    assert any("checking_until" in args[1] for args, _ in writes)


def test_freshness_uses_monitored_branch_and_detects_revision_change(monkeypatch):
    repo = {"id": "id", "url": "https://github.com/sample/repo", "commit_sha": "a" * 40}
    grant = {
        "pk": "repository#id",
        "monitored_branch": "release/stable",
        "branch_explicit": True,
        "checked_at": 0,
    }
    calls = []
    monkeypatch.setattr(github_api.state, "update", lambda *a, **kw: None)

    def request(path, **kwargs):
        calls.append(path)
        return {"sha": "b" * 40, "commit": {"message": "New commit"}}, {}

    monkeypatch.setattr(github_api, "request", request)
    result = github_api.check_update(repo, grant, "user")
    assert result["freshness_status"] == "update_available"
    assert result["remote_sha"] == "b" * 40 and result["remote_message"] == "New commit"
    assert calls == ["/repos/sample/repo/commits/release%2Fstable"]
