"""M5 complete pipeline: evidence, one provider response, validation, optional cache."""
from __future__ import annotations

import json
from typing import Iterator

from repoguide.agent_v2 import gather_evidence
from repoguide.answers_v2 import (
    AnswerResult, abstain, parse_draft, prompt_for_evidence, validate_draft,
)
from repoguide.cache_v2 import load_result, result_key, save_result
from repoguide.provider_v2 import complete, identity, stream


class InvalidGeneration(ValueError):
    pass


def _guard(state: dict) -> AnswerResult | None:
    if not state.get('sources') and not state.get('external_evidence'):
        return abstain(state, 'No usable repository or external evidence was available')
    return None


def _validate_raw(raw: str, state: dict) -> AnswerResult:
    try:
        return validate_draft(parse_draft(raw), state)
    except (ValueError, json.JSONDecodeError) as exc:
        raise InvalidGeneration("Provider did not return a valid structured answer") from exc


def robust_answer(*, repo_id: str, question: str, top_k: int = 8, docs_policy: str = "auto") -> AnswerResult:
    state = gather_evidence(repo_id=repo_id, question=question, top_k=top_k, docs_policy=docs_policy)
    blocked = _guard(state)
    if blocked:
        return blocked

    provider = identity()
    key = result_key(state, provider.provider, provider.model)
    cached = load_result(key)
    if cached is not None:
        answer = AnswerResult.model_validate(cached)
        answer.cached = True
        return answer

    prompt = prompt_for_evidence(state)
    for attempt in range(2):
        raw = complete(prompt if not attempt else prompt + "\nRemember: return ONLY valid JSON, no markdown.")
        try:
            result = _validate_raw(raw, state)
            break
        except InvalidGeneration:
            if attempt:
                return abstain(state, "Provider failed to produce a valid structured response")
    save_result(key, result.model_dump())
    return result


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def stream_robust_answer(*, repo_id: str, question: str, top_k: int = 8, docs_policy: str = "auto") -> Iterator[str]:
    # SSE connection: draft deltas are NOT validated until final. Clients must
    # display a temporary draft and replace it with the verified final event.
    try:
        yield _sse("status", {"stage": "retrieving"})
        state = gather_evidence(repo_id=repo_id, question=question, top_k=top_k, docs_policy=docs_policy)
        yield _sse("status", {"stage": "retrieved", "trace": state.get("trace", [])})
        blocked = _guard(state)
        if blocked:
            yield _sse("final", blocked.model_dump())
            return
        model = identity()
        key = result_key(state, model.provider, model.model)
        cached = load_result(key)
        if cached is not None:
            final = AnswerResult.model_validate(cached)
            final.cached = True
            yield _sse("final", final.model_dump())
            return
        yield _sse("status", {"stage": "generating", "verified": False})
        raw = ""
        for delta in stream(prompt_for_evidence(state)):
            raw += delta
            if len(raw) > 60000:
                raise InvalidGeneration("Model response too large")
            yield _sse("draft_delta", {"text": delta, "verified": False})
        try:
            final = _validate_raw(raw, state)
        except InvalidGeneration:
            final = abstain(state, "Streaming model failed structured-output validation")
        save_result(key, final.model_dump())
        yield _sse("final", final.model_dump())
    except GeneratorExit:
        raise
    except Exception:
        # Do not expose API credentials, model payloads, stack traces, or DB data.
        yield _sse("error", {"message": "RepoGuide could not complete this request"})
