"""M4 continuation: evidence-only LangGraph flow.

No LLM calls. This lets M5 generate once and verify before returning answers.
"""
from __future__ import annotations

import asyncio
import re
from functools import lru_cache
from typing import TypedDict
from urllib.parse import urlparse

from langgraph.graph import START, END, StateGraph
from sqlalchemy import select

from repoguide.agent import retrieve_repository  # reuses M4/M3 indexing pipeline
from repoguide.db import SessionLocal
from repoguide.models import RepoDependency, Repository
from repoguide.routing_v2 import plan
from repoguide.external_tools_v2 import (
    Context7Lookup, GitHubIssueLookup, GitHubLookup, context7_docs,
    github_issue, github_readme,
)


class EvidenceState(TypedDict, total=False):
    repo_id: str
    question: str
    top_k: int
    docs_policy: str
    repo_context: str
    sources: list[dict]
    dependencies: list[str]
    repo_url: str
    commit_sha: str
    routing: dict
    sufficient: bool
    external_evidence: list[dict]
    docs_sources: list[dict]
    errors: list[str]
    trace: list[str]


def read_dependency_metadata(state: EvidenceState) -> dict:
    with SessionLocal() as session:
        repository = session.scalar(select(Repository).where(Repository.id == state["repo_id"]))
        if repository is None:
            raise ValueError("Repository not found")
        deps = session.scalars(select(RepoDependency).where(RepoDependency.repo_id == state["repo_id"])).all()
        names = sorted({d.name for d in deps if d.name})
        return {
            "dependencies": names,
            "repo_url": repository.url,
            "commit_sha": repository.commit_sha,
        }


def choose_tools(state: EvidenceState) -> dict:
    selected = plan(
        state["question"], state.get("sources", []),
        state.get("dependencies", []), state.get("docs_policy", "auto"),
    )
    return {
        "routing": selected.model_dump(),
        "sufficient": selected.sufficient,
        "trace": state.get("trace", []) + [
            f"route: {selected.intent}; tools={','.join(selected.tools) or 'none'}; "
            f"sufficient={selected.sufficient}"
        ],
    }


def tools_or_done(state: EvidenceState) -> str:
    return "external" if state.get("routing", {}).get("tools") else "__end__"


def execute_external(state: EvidenceState) -> dict:
    async def _run():
        items = []
        errors = []
        selected = state.get("routing", {})
        question = state["question"]
        if "context7" in selected.get("tools", []):
            for dep in selected.get("dependencies", [])[:2]:
                try:
                    items.append(await context7_docs(Context7Lookup(
                        library_name=dep, question=question[:400],
                    )))
                except Exception as exc:
                    errors.append(f"Context7/{dep}: {type(exc).__name__}")
        if "github" in selected.get("tools", []):
            parts = urlparse(state["repo_url"]).path.strip("/").split("/")
            if len(parts) == 2:
                owner, repo = parts
                issue_match = re.search(r"(?:issue\s*#?|#)(\d{1,8})\b", question.lower())
                try:
                    if issue_match:
                        items.append(await github_issue(GitHubIssueLookup(
                            owner=owner, repo=repo,
                            issue_number=int(issue_match.group(1)),
                        )))
                    elif any(t in question.lower() for t in ["readme", "upstream docs", "github readme"]):
                        items.append(await github_readme(GitHubLookup(
                            owner=owner, repo=repo, path="README.md",
                            commit_sha=state["commit_sha"],
                        )))
                    else:
                        errors.append("GitHub: query must target README or explicit issue number")
                except Exception as exc:
                    errors.append(f"GitHub: {type(exc).__name__}")
        return items[:3], errors

    items, errors = asyncio.run(_run())
    sources = []
    excerpts = []
    for i, item in enumerate(items, 1):
        label = f"D{i}"
        sources.append({
            "label": label, "library": item.library,
            "topic": item.topic, "title": item.title,
            "url": item.url, "provider": item.provider,
        })
        excerpts.append({"label": label, "excerpt": item.excerpt[:6500], "title": item.title,
                         "url": item.url, "provider": item.provider})
    return {
        "external_evidence": excerpts,
        "docs_sources": sources,
        "errors": errors,
        "trace": state.get("trace", []) + [f"external: {len(excerpts)} sources; {len(errors)} errors"],
    }


@lru_cache(maxsize=1)
def evidence_graph():
    graph = StateGraph(EvidenceState)
    graph.add_node("retrieve", retrieve_repository)
    graph.add_node("dependencies", read_dependency_metadata)
    graph.add_node("route", choose_tools)
    graph.add_node("external", execute_external)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "dependencies")
    graph.add_edge("dependencies", "route")
    graph.add_conditional_edges("route", tools_or_done, {"external": "external", "__end__": END})
    graph.add_edge("external", END)
    return graph.compile()


def gather_evidence(*, repo_id: str, question: str, top_k: int = 8, docs_policy: str = "auto") -> EvidenceState:
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20")
    return evidence_graph().invoke({
        "repo_id": repo_id, "question": question, "top_k": top_k,
        "docs_policy": docs_policy, "trace": [],
    })
