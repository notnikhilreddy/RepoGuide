"""Fixed allowlist of official documentation pages; no user-provided URLs."""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class DocSpec:
    library: str
    topic: str
    title: str
    url: str
    keywords: tuple[str, ...]


DOCUMENTS: tuple[DocSpec, ...] = (
    DocSpec("fastapi", "lifespan", "FastAPI lifespan events",
            "https://fastapi.tiangolo.com/advanced/events/",
            ("fastapi", "lifespan", "startup", "shutdown", "event handler")),
    DocSpec("fastapi", "dependencies", "FastAPI dependencies",
            "https://fastapi.tiangolo.com/tutorial/dependencies/",
            ("fastapi", "dependency injection", "depends", "dependencies")),
    DocSpec("sqlalchemy", "sessions", "SQLAlchemy session basics",
            "https://docs.sqlalchemy.org/en/20/orm/session_basics.html",
            ("sqlalchemy", "sessions", "session", "transaction", "engine")),
    DocSpec("alembic", "migrations", "Alembic migration tutorial",
            "https://alembic.sqlalchemy.org/en/latest/tutorial.html",
            ("alembic", "migration", "migrations", "schema")),
    DocSpec("pgvector", "indexing", "pgvector documentation",
            "https://github.com/pgvector/pgvector",
            ("pgvector", "hnsw", "ivfflat", "vector index")),
    DocSpec("langgraph", "workflows", "LangGraph workflows and agents",
            "https://docs.langchain.com/oss/python/langgraph/workflows-agents",
            ("langgraph", "stategraph", "workflow", "graph agent")),
    DocSpec("mcp", "sdk", "Official MCP Python SDK",
            "https://py.sdk.modelcontextprotocol.io/",
            ("mcp", "model context protocol", "mcpserver", "tool server")),
    DocSpec("uv", "dependencies", "uv dependency management",
            "https://docs.astral.sh/uv/concepts/projects/dependencies/",
            ("uv", "pyproject", "uv add", "uv sync", "dependency management")),
    DocSpec("pydantic", "settings", "Pydantic settings",
            "https://docs.pydantic.dev/latest/concepts/pydantic_settings/",
            ("pydantic", "basesettings", "settingsconfigdict", "env file")),
)

BY_KEY = {(d.library, d.topic): d for d in DOCUMENTS}


def get_doc(library: str, topic: str) -> DocSpec:
    try:
        return BY_KEY[(library, topic)]
    except KeyError as exc:
        raise ValueError("Documentation library/topic is not in the approved catalog") from exc


def choose_docs(question: str, max_docs: int = 2) -> list[DocSpec]:
    """Deterministic routing for a small bounded docs catalog (not an LLM decision)."""
    q = question.lower()
    # Prevent 'uv' from matching substrings such as 'uvicorn'.
    scores = []
    for d in DOCUMENTS:
        score = 0
        for word in d.keywords:
            if re.search(r"(?<![\w])" + re.escape(word) + r"(?![\w])", q):
                score += 3 if word == d.library or len(word) > 8 else 1
        if score:
            scores.append((score, d))
    # If a library has a specific matched topic, avoid another page chosen
    # solely because the library name appears in the question.
    focused = {d.library for score, d in scores if score > 3}
    scores = [(score, d) for score, d in scores
              if not (d.library in focused and score == 3)]
    return [d for _, d in sorted(scores, key=lambda pair: (-pair[0], pair[1].library, pair[1].topic))[:max_docs]]


EXTERNAL_CUES = (
    "official", "documentation", " docs", "recommended", "best practice",
    "migrate", "migration", "upgrade", "deprecated", "deprecation",
    "latest", "current api", "new version", "how should", "compare to docs",
)


def should_use_docs(question: str, policy: str, matches: list[DocSpec]) -> bool:
    if policy == "never" or not matches:
        return False
    if policy == "always":
        return True
    if policy != "auto":
        raise ValueError("Unknown documentation policy")
    q = question.lower()
    return any(cue in q for cue in EXTERNAL_CUES)
