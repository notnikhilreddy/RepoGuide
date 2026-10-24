"""Isolated tests for M7 local-worker bookkeeping (no database/LLM needed)."""
import importlib.util
import sys
import time
import types
from pathlib import Path


def load_jobs(monkeypatch):
    fake_db = types.ModuleType('repoguide.db')
    fake_db.SessionLocal = object()
    fake_indexer = types.ModuleType('repoguide.indexer')
    fake_indexer.index_repository = lambda *a, **kw: None
    monkeypatch.setitem(sys.modules, 'repoguide.db', fake_db)
    monkeypatch.setitem(sys.modules, 'repoguide.indexer', fake_indexer)
    path = Path(__file__).resolve().parents[1] / 'src/repoguide/ui_jobs.py'
    spec = importlib.util.spec_from_file_location('m7_jobs_isolated', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wait_for(jobs, jid):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = jobs.public_job(jid)
        if job['status'] in ('complete', 'failed'):
            return job
        time.sleep(.01)
    raise AssertionError('Job did not finish')


def test_progress_and_success(monkeypatch):
    jobs = load_jobs(monkeypatch)

    def work(emit):
        emit('parsing', 42, 'Parsed 10 chunks')
        emit('embedding', 87, 'Embedded 10 chunks')
        return {'repo_id': 'test-repo'}

    initial = jobs.start('index', work)
    end = wait_for(jobs, initial['id'])
    assert end['status'] == 'complete'
    assert end['result']['repo_id'] == 'test-repo'
    assert [x['stage'] for x in end['events']] == ['starting', 'parsing', 'embedding']
    assert end['percent'] == 100


def test_failure_does_not_leak_exception_content(monkeypatch):
    jobs = load_jobs(monkeypatch)

    def fail(_emit):
        raise RuntimeError('private secret should not appear in response')

    initial = jobs.start('evaluation', fail)
    end = wait_for(jobs, initial['id'])
    assert end['status'] == 'failed'
    assert 'private secret' not in end['detail']
    assert end['error'] == 'RuntimeError'


def test_missing_job(monkeypatch):
    jobs = load_jobs(monkeypatch)
    assert jobs.public_job('nonexistent') is None
