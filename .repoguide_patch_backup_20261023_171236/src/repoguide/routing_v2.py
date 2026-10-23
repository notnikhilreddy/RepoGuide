"""M4 routing. Deterministic baseline; does not require LLM tool-choice tokens.

Treat scores as heuristics, not calibrated probabilities. Tool requests are selected
from approved dependency names and the indexed repository, never arbitrary LLM text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

DOC_TERMS = {"docs", "documentation", "api", "upgrade", "migrate", "migration", "deprecated", "version", "breaking", "latest", "recommended", "best practice", "new syntax", "how should", "currently supported"}
GITHUB_TERMS = {"github", "pull request", "issue", "release", "tag", "commit", "branch", "upstream", "changelog"}
STOP_DEPENDENCIES = {"python", "pip", "setuptools", "typing", "pytest", "requests"}  # these CAN be selected if explicitly named


class RoutePlan(BaseModel):
    intent: str = Field(pattern=r"^(code|documentation|github|mixed)$")
    sufficient: bool
    sufficiency_reason: str
    dependencies: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    explanation: str


@dataclass(frozen=True)
class EvidenceQuality:
    sufficient: bool
    reason: str


def normalize_package(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def select_dependencies(question: str, dependencies: list[str], max_count: int = 2) -> list[str]:
    """Use only packages declared in the repository, matched with word boundaries.

    No fuzzy semantic inference of package names. Generic queries cannot pick a
    random installed dependency. Use manifest-declared names only.
    """
    q = question.lower()
    result: list[str] = []
    for name in dependencies:
        name = name.strip()
        if not name or len(name) > 80 or not re.fullmatch(r"[\w.-]+", name):
            continue
        forms = {name.lower(), name.lower().replace("-", "_"), name.lower().replace("_", "-")}
        if any(re.search(rf"(?<![\w]){re.escape(form)}(?![\w])", q) for form in forms):
            if name not in result:
                result.append(name)
        if len(result) >= max_count:
            break
    return result


def assess_evidence(question: str, sources: list[dict]) -> EvidenceQuality:
    if not sources:
        return EvidenceQuality(False, "no indexed code chunks")
    # A useful baseline: one or more accessible files is necessary, not
    # sufficient for factual completeness. A declaration match is a weak proxy.
    words = set(re.findall(r"[a-z_][a-z_0-9]{3,}", question.lower()))
    paths = [str(s.get("file_path", "")).lower() for s in sources]
    names = [str(s.get("symbol_name") or "").lower() for s in sources]
    hits = sum(bool(words.intersection(set(re.findall(r"[a-z_][a-z_0-9]{3,}", p + " " + n)))) for p, n in zip(paths, names))
    if hits:
        return EvidenceQuality(True, "at least one retrieved file/symbol matches query terms (heuristic)")
    if len(sources) >= 3:
        return EvidenceQuality(True, "multiple repository chunks available (weak heuristic)")
    return EvidenceQuality(False, "few or weakly matched repository chunks")


def plan(question: str, sources: list[dict], declared_deps: list[str], policy: str = "auto") -> RoutePlan:
    if policy not in {"auto", "always", "never"}:
        raise ValueError("Invalid docs policy")
    text = question.lower()
    docs_intent = any(term in text for term in DOC_TERMS)
    github_intent = any(term in text for term in GITHUB_TERMS)
    selected = select_dependencies(question, declared_deps)
    quality = assess_evidence(question, sources)
    # Avoid contacting external servers for pure repository questions. Docs-only
    # intent with no declared package does not make an arbitrary MCP query.
    use_docs = policy != "never" and bool(selected) and (docs_intent or policy == "always" or not quality.sufficient)
    use_github = policy != "never" and github_intent
    tools = (["context7"] if use_docs else []) + (["github"] if use_github else [])
    intent = "mixed" if use_docs and use_github else "github" if use_github else "documentation" if use_docs else "code"
    return RoutePlan(
        intent=intent, sufficient=quality.sufficient, sufficiency_reason=quality.reason,
        dependencies=selected, tools=tools,
        explanation=("Repository-only" if not tools else "External evidence needed: " + ", ".join(tools)),
    )
