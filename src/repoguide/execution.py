"""Bounded request-local diagnostics; works with MLflow disabled at zero idle cost."""

from __future__ import annotations

import math
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

_current = ContextVar("repoguide_execution", default=None)
MAJOR_SPANS = {
    "repoguide.ask",
    "repoguide.ask.stream",
    "agent.evidence_graph",
    "retrieval.hybrid",
    "retrieval.rerank",
    "route.model",
    "mcp.context7",
    "mcp.github",
    "llm.provider.generate",
    "llm.router.complete",
    "answer.validate_citations",
    "index.repository",
    "index.parse_repo",
}


@contextmanager
def request_scope():
    run = {
        "trace_id": uuid.uuid4().hex,
        "started": time.perf_counter(),
        "stages": [],
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_micros": 0,
            "model_calls": 0,
        },
    }
    token = _current.set(run)
    try:
        yield run
    except Exception as exc:
        exc.repoguide_usage = metrics(run)
        raise
    finally:
        _current.reset(token)


def stage(name, started, failed=False):
    run = _current.get()
    if run is not None and len(run["stages"]) < 40 and name in MAJOR_SPANS:
        run["stages"].append(
            {
                "name": name,
                "started_ms": round((started - run["started"]) * 1000),
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "status": "error" if failed else "complete",
            }
        )


def note_usage(provider, model, tokens_in, tokens_out, cached=0):
    run = _current.get()
    if run is None:
        return
    values = run["usage"]
    values["model_calls"] += 1
    if tokens_in is None or tokens_out is None:
        values["incomplete_usage"] = True
        return
    values["input_tokens"] += int(tokens_in)
    values["output_tokens"] += int(tokens_out)
    if provider == "openai" and model == "gpt-6-luna":
        # Standard short-context rates verified Nov 5, 2026. These are estimates,
        # not bills. Unknown models/providers never receive an invented price.
        values["estimated_cost_micros"] += math.ceil(
            max(0, tokens_in - (cached or 0)) * 0.10
            + (cached or 0) * 0.01
            + tokens_out * 0.50
        )
    else:
        values["cost_unavailable"] = True


def metrics(run):
    return {
        **run["usage"],
        "latency_ms": round((time.perf_counter() - run["started"]) * 1000),
    }
