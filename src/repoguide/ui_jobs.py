"""Local-development, in-process indexing/evaluation jobs.

NOT a durable job queue. State disappears on restart; replace with Redis/Celery/RQ
and tenant authentication before public hosting.
"""
from __future__ import annotations
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from repoguide.db import SessionLocal
from repoguide.indexer import index_repository

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="repoguide-ui")
_lock = threading.RLock()
_jobs: dict[str, dict] = {}


def start(kind: str, worker: Callable[[Callable[[str, int, str], None]], dict]) -> dict:
    jid = str(uuid.uuid4())
    job = {"id": jid, "kind": kind, "status": "queued", "stage": "queued",
           "percent": 0, "detail": "Waiting for worker", "created_at": time.time(),
           "updated_at": time.time(), "result": None, "error": None,
           "events": []}
    with _lock:
        # In-memory data only; bounded history.
        stale = sorted(_jobs.values(), key=lambda j: j['created_at'])[:-100]
        for old in stale:
            if old['status'] in ('complete', 'failed'):
                _jobs.pop(old['id'], None)
        _jobs[jid] = job

    def emit(stage: str, percent: int, detail: str):
        with _lock:
            j = _jobs[jid]
            j.update(stage=stage, percent=min(100, max(0, int(percent))),
                     detail=str(detail)[:280], updated_at=time.time(), status='running')
            j['events'].append({"stage": stage, "percent": j['percent'], "detail": j['detail'],
                                "time": j['updated_at']})
            j['events'] = j['events'][-120:]

    def run():
        try:
            emit('starting', 1, 'Worker started')
            result = worker(emit)
            with _lock:
                _jobs[jid].update(result=result, status='complete', stage='complete',
                                  percent=100, updated_at=time.time(), detail='Completed')
        except Exception as e:
            # Never send raw error traces/secrets to browser.
            with _lock:
                _jobs[jid].update(status='failed', stage='failed', error=type(e).__name__,
                                  detail=f'Job failed ({type(e).__name__}); check server logs',
                                  updated_at=time.time())
            import logging
            logging.getLogger(__name__).exception('UI job %s failed', jid)
    _executor.submit(run)
    return public_job(jid)


def public_job(jid: str) -> dict | None:
    with _lock:
        if jid not in _jobs:
            return None
        return dict(_jobs[jid])


def begin_index(url: str, force: bool = False) -> dict:
    def run(emit):
        with SessionLocal() as session:
            repo = index_repository(url, session, force=force, progress=emit)
            return {"repo_id": repo.id, "url": repo.url, "commit_sha": repo.commit_sha}
    return start('index', run)


def begin_evaluation(repo_id: str, dataset: Path, case_limit: int) -> dict:
    from repoguide.pipeline import answer
    from evals.quality_metrics import hit_at_k, file_recall, mrr, citations_ok
    def run(emit):
        cases = json.loads(dataset.read_text(encoding='utf-8'))[:case_limit]
        if not isinstance(cases, list) or not cases:
            raise ValueError('No cases in dataset')
        results=[]
        for i, case in enumerate(cases):
            emit('evaluating', round(5 + 88 * i / len(cases)), f'Question {i+1}/{len(cases)}')
            t0=time.perf_counter()
            r=answer(repo_id=repo_id, question=case['question'], top_k=8,
                     docs_policy=case.get('docs_policy', 'never'),retrieval_mode='hybrid')
            paths=[s['file_path'] for s in r.sources]
            expected=case['expected_paths']
            results.append({'question':case['question'], 'hit_at_8':hit_at_k(expected,paths,8),
                            'file_recall_at_8':file_recall(expected,paths,8),
                            'mrr_at_8':mrr(expected,paths,8),
                            'citations_valid':citations_ok(r.answer,r.sources+r.docs_sources),
                            'status':r.status,'trace_id':r.trace_id,
                            'latency_ms':round((time.perf_counter()-t0)*1000),
                            'observed_paths':paths,'expected_paths':expected,
                            'answer':r.answer})
        emit('saving', 96, 'Saving benchmark results')
        out = Path('evals/m7_latest_results.json')
        out.write_text(json.dumps(results,indent=2),encoding='utf-8')
        # Optional MLflow experiment run, while per-request traces were already recorded.
        try:
            import mlflow
            from repoguide.telemetry import setup_mlflow
            setup_mlflow()
            with mlflow.start_run(run_name='RepoGuide-M7-UI-evaluation'):
                import statistics
                mlflow.log_params({'dataset':dataset.name,'repo_id':repo_id,'cases':len(results),'mode':'hybrid'})
                for metric in ('hit_at_8','file_recall_at_8','mrr_at_8'):
                    mlflow.log_metric(metric,statistics.mean(float(x[metric]) for x in results))
                mlflow.log_metric('citation_valid_rate',statistics.mean(float(x['citations_valid']) for x in results))
                mlflow.log_metric('latency_median_ms',statistics.median(x['latency_ms'] for x in results))
                mlflow.log_dict(results,'evaluations/results.json')
        except Exception:
            import logging
            logging.getLogger(__name__).exception('MLflow metric logging unavailable')
        return {'dataset':dataset.name,'count':len(results),'results':results}
    return start('evaluation',run)
