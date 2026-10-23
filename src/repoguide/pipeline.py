"""Single production-shaped answer path shared by /ask, /robust and /stream.

All information gathering is via one LangGraph; generation occurs exactly once
per successful request and is followed by deterministic validation.
"""
from __future__ import annotations

import json
import re
from typing import Iterator

from repoguide.answers import AnswerResult, abstain, parse_draft, prompt_for_evidence, validate_draft
from repoguide.cache import load_result, result_key, save_result
from repoguide.provider import complete, identity, stream
from repoguide.telemetry import feedback, record, span
from repoguide.workflow import gather_evidence


class InvalidGeneration(ValueError):
    pass


def _depth(question: str, requested: str) -> str:
    if requested != 'auto':
        return requested
    if len(question.split()) > 16 or re.search(r'\b(explain in detail|architecture|end.to.end|entire flow|walk through)\b', question, re.I):
        return 'detailed'
    return 'standard'


def _validate(raw: str, state: dict, depth: str) -> AnswerResult:
    with span('answer.validate_citations', 'CHAIN', {'raw': raw, 'evidence_labels':[s['label'] for s in state.get('sources',[])+state.get('docs_sources',[])]}) as v:
        try:
            result=validate_draft(parse_draft(raw), state)
        except (ValueError, json.JSONDecodeError) as exc:
            record(v, {'valid':False}, failure_type=type(exc).__name__)
            raise InvalidGeneration('Provider response did not validate') from exc
        result.answer_depth=depth
        record(v, {'status':result.status,'verified':result.verified_labels, 'rejected':result.rejected_labels}, citation_count=len(result.verified_labels))
        return result


def _cache_key(state: dict, depth: str, tenant: str) -> str:
    provider=identity()
    state={**state, 'question': state['question'] + f'|answer_depth={depth}|tenant={tenant}|prompt=v6'}
    return result_key(state,provider.provider,provider.model)


def _gather(repo_id, question, top_k, docs_policy, retrieval_mode):
    with span('agent.evidence_graph', 'AGENT', {'repo_id':repo_id,'question':question,'top_k':top_k,'docs_policy':docs_policy,'retrieval_mode':retrieval_mode}) as sp:
        data=gather_evidence(repo_id=repo_id,question=question,top_k=top_k,docs_policy=docs_policy,retrieval_mode=retrieval_mode)
        record(sp, {'trace':data.get('trace',[]),'files':[x['file_path'] for x in data.get('sources',[])]}, external_count=len(data.get('external_evidence',[])))
        return data


def answer(*,repo_id:str,question:str,top_k:int=8,docs_policy:str='auto',retrieval_mode:str='hybrid',answer_depth:str='auto',tenant:str='local') -> AnswerResult:
    depth=_depth(question,answer_depth)
    with span('repoguide.ask', 'CHAIN', {'repo_id':repo_id,'question':question,'top_k':top_k,'docs_policy':docs_policy,'retrieval_mode':retrieval_mode,'answer_depth':depth}, {'pipeline.version':'6','tenant':tenant}) as root:
        state=_gather(repo_id,question,top_k,docs_policy,retrieval_mode)
        if not state.get('sources') and not state.get('external_evidence'):
            output=abstain(state,'No usable evidence')
        else:
            key=_cache_key(state,depth,tenant)
            with span('cache.lookup','CACHE',{'key_digest':key[-12:]}) as cache_span:
                cached=load_result(key)
                record(cache_span, {'hit':bool(cached)}, cache_hit=bool(cached))
            if cached:
                output=AnswerResult.model_validate(cached)
                output.cached=True
            else:
                prompt=prompt_for_evidence(state,depth)
                try:
                    with span('answer.generate','LLM',{'prompt':prompt},{'provider':identity().provider,'model':identity().model}) as gen:
                        raw=complete(prompt)
                        record(gen, {'generated':raw}, output_chars=len(raw))
                    output=_validate(raw,state,depth)
                except InvalidGeneration:
                    # Do not run a second paid generation automatically.
                    output=abstain(state,'Could not validate generated structured answer')
                if output.status != 'insufficient_evidence':
                    with span('cache.store','CACHE',{'key_digest':key[-12:]}) as write:
                        save_result(key,output.model_dump(exclude={'trace_id'}))
                        record(write, {'stored':True})
        output.answer_depth=depth
        output.trace_id=str(getattr(root,'trace_id','')) or None
        record(root,output.model_dump(),status=output.status,source_count=len(output.sources),doc_count=len(output.docs_sources),cache_hit=output.cached)
        if output.trace_id:
            try:
                feedback(output.trace_id,'citations_valid',not bool(output.rejected_labels), 'Deterministic label membership only')
            except Exception:
                pass
        return output


def _event(event:str,payload:dict)->str:
    return f'event: {event}\ndata: {json.dumps(payload,ensure_ascii=False,default=str)}\n\n'


def stream_answer(*, repo_id:str,question:str,top_k:int=8,docs_policy:str='auto',retrieval_mode:str='hybrid',answer_depth:str='auto',tenant:str='local')->Iterator[str]:
    """SSE: status and provisional draft events; final is authoritative.

    Generation remains single-pass. The draft is unverified and must be replaced
    in the UI by the validated final response or discarded on error.
    """
    depth=_depth(question,answer_depth)
    try:
        with span('repoguide.ask.stream','CHAIN',{'repo_id':repo_id,'question':question,'depth':depth}) as root:
            yield _event('status',{'step':'retrieving'})
            state=_gather(repo_id,question,top_k,docs_policy,retrieval_mode)
            if not state.get('sources') and not state.get('external_evidence'):
                final=abstain(state,'No usable evidence')
            else:
                key=_cache_key(state,depth,tenant)
                with span('cache.lookup','CACHE',{'key_digest':key[-12:]}) as cache_span:
                    cached=load_result(key)
                    record(cache_span, {'hit':bool(cached)})
                if cached:
                    final=AnswerResult.model_validate(cached);final.cached=True
                else:
                    prompt=prompt_for_evidence(state,depth)
                    yield _event('status',{'step':'generating','verified':False})
                    fragments=[]; length=0
                    with span('answer.generate.stream','LLM',{'prompt':prompt},{'model':identity().model}) as gen:
                        for delta in stream(prompt):
                            length+=len(delta)
                            if length>60000:
                                raise InvalidGeneration('Response exceeds size limit')
                            fragments.append(delta)
                            yield _event('draft_delta',{'text':delta,'verified':False})
                        record(gen, {'response': ''.join(fragments)}, characters=length)
                    try:
                        final=_validate(''.join(fragments),state,depth)
                    except InvalidGeneration:
                        final=abstain(state,'Streaming output failed validation')
                    if final.status != 'insufficient_evidence':
                        with span('cache.store','CACHE',{'key_digest':key[-12:]}) as w:
                            save_result(key,final.model_dump(exclude={'trace_id'}));record(w,{'stored':True})
            final.trace_id=str(getattr(root,'trace_id','')) or None
            final.answer_depth=depth
            record(root,final.model_dump(),status=final.status)
            yield _event('final',final.model_dump())
    except GeneratorExit:
        raise
    except Exception:
        yield _event('error',{'message':'RepoGuide could not complete the request'})
