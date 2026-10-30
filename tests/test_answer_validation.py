import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://repoguide:repoguide@localhost:5432/repoguide"
)
os.environ["MLFLOW_ENABLED"] = "false"
from repoguide.evaluation_metrics import citations_ok, file_recall, hit_at_k, mrr
from repoguide.router import parse_decision
from repoguide.telemetry import safe


def test_router_only_approved_dependencies():
    p = parse_decision(
        {
            "intent": "mixed",
            "sufficient": False,
            "tools": ["context7", "github"],
            "dependencies": ["fastapi", "unknown"],
            "reason": "docs",
        },
        ["fastapi"],
        "auto",
    )
    assert p.dependencies == ["fastapi"]
    assert p.tools == ["context7", "github"]


def test_router_policy_never():
    p = parse_decision(
        {
            "intent": "documentation",
            "sufficient": False,
            "tools": ["context7"],
            "dependencies": ["fastapi"],
            "reason": "docs",
        },
        ["fastapi"],
        "never",
    )
    assert p.tools == []


def test_router_rejects_unknown_tool():
    import pytest

    with pytest.raises(Exception):
        parse_decision(
            {
                "intent": "code",
                "sufficient": True,
                "tools": ["delete_repository"],
                "reason": "test",
            },
            [],
            "auto",
        )


def test_metrics():
    assert hit_at_k(["a.py"], ["b.py", "a.py"], 2) == 1
    assert mrr(["a.py"], ["b.py", "a.py"], 2) == 0.5
    assert file_recall(["a.py", "c.py"], ["a.py"], 5) == 0.5
    assert citations_ok("Works [S1]", [{"label": "S1"}])
    assert not citations_ok("Wrong [S999]", [{"label": "S1"}])


def test_redaction():
    assert safe({"api_key": "supersecret"})["api_key"] == "[REDACTED]"
