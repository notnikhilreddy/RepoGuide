"""Mock expensive services inside a scoped fixture; never contaminate other tests."""
import importlib
import os
import sys
import types

import pytest

os.environ.setdefault('DATABASE_URL','postgresql+psycopg://repoguide:repoguide@localhost:5432/repoguide')
os.environ['MLFLOW_ENABLED']='false'


@pytest.fixture
def pipeline(monkeypatch):
    stub=types.ModuleType('repoguide.workflow')
    stub.gather_evidence=lambda **kw: {
        'repo_id':kw['repo_id'],'question':kw['question'],'commit_sha':'a'*40,
        'sources':[{'label':'S1','file_path':'src/example.py','start_line':1,'end_line':5}],
        'repo_context':'[S1] FILE: src/example.py\nLINES: 1-5\ndef get_user(): return True',
        'external_evidence':[],'docs_sources':[],
        'routing':{'tools':[]},'docs_policy':kw['docs_policy'],'trace':['test:evidence'],
    }
    original_pipeline=sys.modules.pop('repoguide.pipeline',None)
    monkeypatch.setitem(sys.modules,'repoguide.workflow',stub)
    try:
        yield importlib.import_module('repoguide.pipeline')
    finally:
        sys.modules.pop('repoguide.pipeline',None)
        if original_pipeline is not None:
            sys.modules['repoguide.pipeline']=original_pipeline


def test_answer_one_generation(pipeline, monkeypatch):
    calls=[]
    monkeypatch.setattr(pipeline,'load_result',lambda key:None)
    monkeypatch.setattr(pipeline,'save_result',lambda *a,**k:None)
    monkeypatch.setattr(pipeline,'complete',lambda prompt:(calls.append(prompt) or '{"status":"answered","answer":"`get_user` returns True [S1]","claims":[{"text":"It returns True","citations":["S1"]}],"limitations":[]}'))
    result=pipeline.answer(repo_id='repo1',question='What does get_user do?',docs_policy='never')
    assert result.status=='answered'
    assert result.verified_labels==['S1']
    assert len(calls)==1


def test_invalid_reference_no_extra_generation(pipeline, monkeypatch):
    count=[]
    monkeypatch.setattr(pipeline,'load_result',lambda key:None)
    monkeypatch.setattr(pipeline,'save_result',lambda *a,**k:None)
    monkeypatch.setattr(pipeline,'complete',lambda prompt:(count.append(1) or '{"status":"answered","answer":"Invented [S99]","claims":[],"limitations":[]}'))
    result=pipeline.answer(repo_id='repo1',question='What does get_user do?',docs_policy='never')
    assert result.status=='insufficient_evidence'
    assert len(count)==1
