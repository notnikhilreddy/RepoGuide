"""Mock data access, MCP calls and Gemini so these tests are offline and free."""
import sys
from types import SimpleNamespace
import pytest


@pytest.fixture()
def agent_module(monkeypatch):
    # agent imports LangGraph; these tests require the installed langgraph package.
    from repoguide import agent

    class DummySession:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    chunk = SimpleNamespace(
        id="c1", file_path="src/repoguide/indexer.py",
        symbol_name="index_repository", content="def index_repository(): pass",
        start_line=1, end_line=1,
    )
    hit = SimpleNamespace(chunk=chunk, origin="hybrid", distance=0.12,
                          channels=("dense", "keyword"), fusion_score=0.02,
                          rerank_score=None)
    packed = SimpleNamespace(hit=hit, content=chunk.content, end_line=1)
    monkeypatch.setattr(agent, "SessionLocal", DummySession)
    monkeypatch.setattr(agent, "search", lambda **kw: [hit])
    monkeypatch.setattr(agent, "pack_context", lambda *args, **kwargs: [packed])
    monkeypatch.setattr(agent, "generate_agent_answer", lambda prompt: "Mock answer [S1].")
    return agent


def test_no_docs_on_repo_only_question(agent_module, monkeypatch):
    def fail_if_called(*args):
        raise AssertionError("MCP should not run")
    monkeypatch.setattr(agent_module, "fetch_official_docs", fail_if_called)
    result = agent_module.answer_with_agent(
        repo_id="repo", question="How does indexing reach the database?",
    )
    assert result["sources"][0]["label"] == "S1"
    assert result["docs_sources"] == []
    assert "route: repository_only" in result["trace"]


def test_documentation_path(agent_module, monkeypatch):
    async def fake_docs(specs):
        doc = specs[0]
        return ([{"library": doc.library, "topic": doc.topic,
                  "title": doc.title, "url": doc.url, "excerpt": "Use lifespan."}], [])
    monkeypatch.setattr(agent_module, "fetch_official_docs", fake_docs)
    result = agent_module.answer_with_agent(
        repo_id="repo", question="How should FastAPI startup migrate to lifespan?",
    )
    assert result["docs_sources"][0]["label"] == "D1"
    assert "route: official_docs" in result["trace"]


def test_docs_failure_falls_back(agent_module, monkeypatch):
    async def failed(_):
        raise RuntimeError("offline")
    monkeypatch.setattr(agent_module, "fetch_official_docs", failed)
    result = agent_module.answer_with_agent(
        repo_id="repo", question="What do official FastAPI lifespan docs say?",
    )
    assert result["sources"]
    assert not result["docs_sources"]
    assert any("failures" in step for step in result["trace"])
