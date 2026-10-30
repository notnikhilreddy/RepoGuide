"""One LangGraph evidence graph (no generation or duplicated provider calls)."""

from __future__ import annotations

import asyncio
import re
from functools import lru_cache
from typing import TypedDict
from urllib.parse import urlparse

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from repoguide.cache import load_tool, save_tool, tool_cache_key
from repoguide.config import settings
from repoguide.context import pack_context
from repoguide.db import SessionLocal
from repoguide.external_tools_v2 import (
    Context7Lookup,
    GitHubIssueLookup,
    GitHubLookup,
    context7_docs,
    github_issue,
    github_readme,
)
from repoguide.hybrid import search
from repoguide.models import RepoDependency, Repository
from repoguide.retrieval_exact import exact_symbols
from repoguide.router import decide
from repoguide.telemetry import record, span


class EvidenceState(TypedDict, total=False):
    repo_id: str
    question: str
    top_k: int
    docs_policy: str
    retrieval_mode: str
    repo_context: str
    sources: list[dict]
    dependencies: list[str]
    dependency_specs: dict[str, str]
    repo_url: str
    commit_sha: str
    routing: dict
    external_evidence: list[dict]
    docs_sources: list[dict]
    errors: list[str]
    trace: list[str]


def retrieve_node(state: EvidenceState) -> dict:
    with span(
        "retrieval.hybrid",
        "RETRIEVER",
        {
            "question": state["question"],
            "repo_id": state["repo_id"],
            "mode": state.get("retrieval_mode", "hybrid"),
        },
    ) as active:
        with SessionLocal() as session:
            hits = search(
                session=session,
                repo_id=state["repo_id"],
                question=state["question"],
                top_k=state["top_k"],
                retrieval_mode=state.get("retrieval_mode", "hybrid"),
            )
            exact = exact_symbols(session, state["repo_id"], state["question"])
            seen = set()
            hits = [
                h
                for h in exact + hits
                if not (h.chunk.id in seen or seen.add(h.chunk.id))
            ][: state["top_k"]]
            record(
                active,
                {"candidate_paths": [x.chunk.file_path for x in hits]},
                hit_count=len(hits),
                dense_distances=[x.distance for x in hits if x.distance is not None],
                rrf_scores=[x.fusion_score for x in hits if x.fusion_score is not None],
                rerank_scores=[
                    x.rerank_score for x in hits if x.rerank_score is not None
                ],
            )
            with span(
                "retrieval.context_pack",
                "CHAIN",
                {"chunk_ids": [h.chunk.id for h in hits]},
            ) as pack_span:
                packed = pack_context(hits, max_chars=settings.context_char_budget)
                record(
                    pack_span,
                    {
                        "packed_count": len(packed),
                        "context_chars": sum(len(i.content) for i in packed),
                    },
                )
        sections = []
        sources = []
        for i, item in enumerate(packed, 1):
            c = item.hit.chunk
            sources.append(
                {
                    "label": f"S{i}",
                    "file_path": c.file_path,
                    "symbol_name": c.symbol_name,
                    "start_line": c.start_line,
                    "end_line": item.end_line,
                    "origin": item.hit.origin,
                    "channels": list(item.hit.channels),
                    "distance": item.hit.distance,
                    "fusion_score": item.hit.fusion_score,
                    "rerank_score": item.hit.rerank_score,
                }
            )
            sections.append(
                f"[S{i}] FILE: {c.file_path}\nSYMBOL: {c.symbol_name or 'module'}\nLINES: {c.start_line}-{item.end_line}\n{item.content}"
            )
        return {
            "sources": sources,
            "repo_context": "\n\n---\n\n".join(sections),
            "trace": state.get("trace", []) + [f"retrieval: {len(sources)} chunks"],
        }


def dependency_node(state: EvidenceState) -> dict:
    with span(
        "repository.metadata", "RETRIEVER", {"repo_id": state["repo_id"]}
    ) as active:
        with SessionLocal() as session:
            repo = session.scalar(
                select(Repository).where(Repository.id == state["repo_id"])
            )
            if repo is None:
                raise ValueError("Repository not found")
            rows = session.scalars(
                select(RepoDependency).where(RepoDependency.repo_id == repo.id)
            ).all()
        specs = {d.name: d.spec for d in rows if d.name}
        result = {
            "dependencies": sorted(specs),
            "dependency_specs": specs,
            "repo_url": repo.url,
            "commit_sha": repo.commit_sha,
        }
        record(
            active,
            {"deps": specs, "commit_sha": repo.commit_sha},
            dependency_count=len(specs),
        )
        return result


def route_node(state: EvidenceState) -> dict:
    plan = decide(
        state["question"],
        state.get("sources", []),
        state.get("dependencies", []),
        state.get("docs_policy", "auto"),
    )
    return {
        "routing": plan.model_dump(),
        "trace": state.get("trace", [])
        + [f"route: {plan.intent} via {plan.router}; tools={plan.tools}"],
    }


def external_or_finish(state: EvidenceState):
    return "external" if state.get("routing", {}).get("tools") else "__end__"


def external_node(state: EvidenceState) -> dict:
    async def calls():
        results = []
        errors = []
        route = state["routing"]
        question = state["question"]
        if "context7" in route["tools"]:
            for dep in route.get("dependencies", [])[:2]:
                try:
                    with span(
                        "mcp.context7",
                        "TOOL",
                        {"library": dep, "question": question},
                        {
                            "dependency.spec": state.get("dependency_specs", {}).get(
                                dep, ""
                            )
                        },
                    ) as active:
                        key = tool_cache_key(
                            "context7",
                            {
                                "dependency": dep,
                                "question": question[:400],
                                "version": state.get("dependency_specs", {}).get(
                                    dep, ""
                                ),
                            },
                        )
                        cached = load_tool(key)
                        if cached:
                            from repoguide.external_tools_v2 import ExternalEvidence

                            item = ExternalEvidence(**cached)
                        else:
                            item = await context7_docs(
                                Context7Lookup(
                                    library_name=dep, question=question[:400]
                                )
                            )
                            save_tool(key, item.__dict__, ttl=1800)
                        record(
                            active,
                            {"url": item.url, "excerpt": item.excerpt},
                            provider="context7",
                            cache_hit=bool(cached),
                        )
                        results.append(item)
                except Exception as exc:
                    errors.append(f"context7/{dep}: {type(exc).__name__}")
        if "github" in route["tools"]:
            parts = urlparse(state["repo_url"]).path.strip("/").split("/")
            if len(parts) == 2:
                owner, repo = parts
                match = re.search(r"(?:issue\s*#?|#)(\d{1,8})\b", question, re.I)
                try:
                    with span(
                        "mcp.github",
                        "TOOL",
                        {
                            "repo": state["repo_url"],
                            "issue": match.group(1) if match else "README",
                        },
                        {"readonly": True},
                    ) as active:
                        if match:
                            item = await github_issue(
                                GitHubIssueLookup(
                                    owner=owner,
                                    repo=repo,
                                    issue_number=int(match.group(1)),
                                )
                            )
                        else:
                            item = await github_readme(
                                GitHubLookup(
                                    owner=owner,
                                    repo=repo,
                                    path="README.md",
                                    commit_sha=state["commit_sha"],
                                )
                            )
                        record(active, {"url": item.url, "excerpt": item.excerpt})
                        results.append(item)
                except Exception as exc:
                    errors.append(f"github: {type(exc).__name__}")
        return results[:3], errors

    items, errors = asyncio.run(calls())
    excerpts = []
    sources = []
    for i, item in enumerate(items, 1):
        label = f"D{i}"
        sources.append(
            {
                "label": label,
                "library": item.library,
                "topic": item.topic,
                "title": item.title,
                "url": item.url,
                "provider": item.provider,
            }
        )
        excerpts.append(
            {
                "label": label,
                "title": item.title,
                "url": item.url,
                "excerpt": item.excerpt[:6500],
                "provider": item.provider,
            }
        )
    return {
        "external_evidence": excerpts,
        "docs_sources": sources,
        "errors": errors,
        "trace": state.get("trace", [])
        + [f"external: {len(excerpts)} docs; {len(errors)} errors"],
    }


@lru_cache(maxsize=1)
def graph():
    workflow = StateGraph(EvidenceState)
    for n, fn in [
        ("retrieve", retrieve_node),
        ("metadata", dependency_node),
        ("route", route_node),
        ("external", external_node),
    ]:
        workflow.add_node(n, fn)
    workflow.add_edge(START, "retrieve")
    workflow.add_edge("retrieve", "metadata")
    workflow.add_edge("metadata", "route")
    workflow.add_conditional_edges(
        "route", external_or_finish, {"external": "external", "__end__": END}
    )
    workflow.add_edge("external", END)
    return workflow.compile()


def gather_evidence(
    *,
    repo_id: str,
    question: str,
    top_k: int = 8,
    docs_policy: str = "auto",
    retrieval_mode: str = "hybrid",
) -> EvidenceState:
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be 1..20")
    return graph().invoke(
        {
            "repo_id": repo_id,
            "question": question,
            "top_k": top_k,
            "docs_policy": docs_policy,
            "retrieval_mode": retrieval_mode,
            "trace": [],
        }
    )
