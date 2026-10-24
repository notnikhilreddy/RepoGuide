"""Read-only UI adapters and localhost-only development jobs for RepoGuide M7.

No fabricated repository content. Existing old indexes expose a clearly marked
partial reconstruction until refreshed with a source snapshot.
"""
from __future__ import annotations
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import func, select

from repoguide.db import SessionLocal
from repoguide.models import Chunk, CodeEdge, CodeSymbol, RepoDependency, Repository, SourceFile
from repoguide.ui_jobs import public_job, begin_index, begin_evaluation

router=APIRouter(prefix='/api/ui',tags=['UI'])


def _repo(db, repo_id):
    repo=db.get(Repository,repo_id)
    if repo is None: raise HTTPException(404,'Repository not found')
    return repo


def _local_only(request:Request):
    # Defensive in the absence of auth; still bind Uvicorn to 127.0.0.1.
    if not request.client or request.client.host not in ('127.0.0.1','::1','localhost'):
        raise HTTPException(403,'Local development only; authentication required for hosting')


@router.get('/repositories')
def repositories(limit:int=Query(30,ge=1,le=100)):
    with SessionLocal() as db:
        rows=db.scalars(select(Repository).order_by(Repository.created_at.desc()).limit(limit)).all()
        ids=[r.id for r in rows]
        counts={}
        for model,key in ((Chunk,'chunks'),(CodeSymbol,'symbols'),(CodeEdge,'edges'),
                          (RepoDependency,'dependencies'),(SourceFile,'files')):
            data=db.execute(select(model.repo_id,func.count()).where(model.repo_id.in_(ids)).group_by(model.repo_id)).all() if ids else []
            for rid,count in data:
                counts.setdefault(rid,{})[key]=count
        return [{'id':r.id,'url':r.url,'name':'/'.join(urlparse(r.url).path.strip('/').split('/')[-2:]),
                 'commit_sha':r.commit_sha,'status':r.status,
                 'created_at':r.created_at.isoformat() if r.created_at else None,
                 'counts':counts.get(r.id,{})} for r in rows]


@router.get('/repositories/{repo_id}/overview')
def overview(repo_id:str):
    with SessionLocal() as db:
        r=_repo(db,repo_id)
        totals={}
        for model,key in ((Chunk,'chunks'),(CodeSymbol,'symbols'),(CodeEdge,'edges'),
                          (RepoDependency,'dependencies'),(SourceFile,'files')):
            totals[key]=db.scalar(select(func.count()).select_from(model).where(model.repo_id==repo_id)) or 0
        kinds=db.execute(select(CodeEdge.kind,func.count()).where(CodeEdge.repo_id==repo_id).group_by(CodeEdge.kind)).all()
        langs=db.execute(select(CodeSymbol.language,func.count()).where(CodeSymbol.repo_id==repo_id).group_by(CodeSymbol.language)).all()
        return {'id':r.id,'url':r.url,'commit_sha':r.commit_sha,'status':r.status,
                'counts':totals,'edge_types':dict(kinds),'languages':dict(langs),
                'has_exact_sources':bool(totals['files'])}


@router.get('/repositories/{repo_id}/files')
def files(repo_id:str):
    with SessionLocal() as db:
        _repo(db,repo_id)
        snaps=db.execute(select(SourceFile.path,SourceFile.byte_count).where(SourceFile.repo_id==repo_id)).all()
        indexed=db.execute(select(Chunk.file_path,func.count()).where(Chunk.repo_id==repo_id).group_by(Chunk.file_path)).all()
        bypath={str(path):{'path':str(path),'bytes':int(size),'exact':True,'chunks':0} for path,size in snaps}
        for path,count in indexed:
            item=bypath.setdefault(str(path),{'path':str(path),'bytes':None,'exact':False,'chunks':0})
            item['chunks']=int(count)
        return sorted(bypath.values(),key=lambda x:x['path'])


@router.get('/repositories/{repo_id}/file')
def file_content(repo_id:str,path:str=Query(min_length=1,max_length=1000)):
    if path.startswith('/') or '..' in path.split('/') or '\\' in path or '\x00' in path:
        raise HTTPException(400,'Invalid path')
    with SessionLocal() as db:
        _repo(db,repo_id)
        snap=db.get(SourceFile,(repo_id,path))
        if snap:
            return {'path':path,'content':snap.content,'partial':False,'lines':snap.content.count('\n')+1,
                    'byte_count':snap.byte_count}
        chunks=db.scalars(select(Chunk).where(Chunk.repo_id==repo_id,Chunk.file_path==path)
                          .order_by(Chunk.start_line,Chunk.end_line).limit(500)).all()
        if not chunks: raise HTTPException(404,'File not in indexed repository')
        lines={}
        for c in chunks:
            for pos,text in enumerate(c.content.splitlines(),c.start_line):
                lines.setdefault(pos,text)
        limit=min(max(lines),4000)
        content='\n'.join(lines.get(i,'') for i in range(1,limit+1))
        return {'path':path,'content':content,'partial':True,'lines':limit,
                'byte_count':None, 'note':'Reconstructed from indexed chunks; missing lines may be blank. Reindex to capture exact source.'}


@router.get('/repositories/{repo_id}/symbols-in-file')
def symbols_in_file(repo_id:str,path:str=Query(min_length=1)):
    with SessionLocal() as db:
        _repo(db,repo_id)
        rows=db.scalars(select(CodeSymbol).where(CodeSymbol.repo_id==repo_id,CodeSymbol.file_path==path)
                        .order_by(CodeSymbol.start_line).limit(250)).all()
        return [{'id':s.id,'name':s.name,'qualified_name':s.qualified_name,'kind':s.kind,
                 'start_line':s.start_line,'end_line':s.end_line} for s in rows]


# Explicit filenames, never arbitrary filesystem access from a query param.
DATASETS=('m3_cases.json','mcp_route_cases.json','retrieval.json')
REPORTS=('m3_results.json','m5_live_results.json','m6_results.json','m7_latest_results.json')


def _eval_root():
    return Path(__file__).resolve().parents[2] / 'evals'


@router.get('/evaluations')
def evaluation_catalog():
    root=_eval_root(); datasets=[];reports=[]
    for filename in DATASETS:
        p=root/filename
        if p.is_file():
            try:
                v=json.loads(p.read_text()); datasets.append({'name':filename,'cases':len(v) if isinstance(v,list) else 0})
            except (ValueError,OSError): pass
    for filename in REPORTS:
        p=root/filename
        if p.is_file():
            try:
                v=json.loads(p.read_text()); reports.append({'name':filename,'cases':len(v) if isinstance(v,list) else int(v.get('query_count',0)) if isinstance(v,dict) else 0})
            except (ValueError,OSError): pass
    return {'datasets':datasets,'reports':reports}


@router.get('/evaluations/reports/{name}')
def evaluation_report(name:str):
    if name not in REPORTS:raise HTTPException(404,'Unknown report')
    p=_eval_root()/name
    if not p.is_file():raise HTTPException(404,'Report not found')
    raw=json.loads(p.read_text(encoding='utf-8'))
    if isinstance(raw,dict):
        # Milestone 3 benchmark artifact stores aggregates grouped by retrieval mode.
        return {'name':name,'results':[], 'aggregate':raw.get('aggregate',{}),
                'details':raw.get('details',{}),'notes':raw.get('notes','')}
    if not isinstance(raw,list):raise HTTPException(422,'Unexpected report format')
    return {'name':name,'results':raw[:200], 'aggregate':{},'details':{}}


class NewIndex(BaseModel):
    url: HttpUrl
    force: bool = False


@router.post('/index-jobs',status_code=202)
def create_index(request:Request,payload:NewIndex):
    _local_only(request)
    from repoguide.git_utils import parse_github_url
    try:parse_github_url(str(payload.url))
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    return begin_index(str(payload.url),payload.force)


@router.get('/jobs/{job_id}')
def job_status(job_id:str):
    item=public_job(job_id)
    if item is None:raise HTTPException(404,'Unknown or expired job')
    return item


class NewEvaluation(BaseModel):
    repo_id: str
    dataset: str = 'm3_cases.json'
    limit: int = Field(default=5,ge=1,le=20)


@router.post('/evaluation-jobs',status_code=202)
def create_eval(request:Request,payload:NewEvaluation):
    _local_only(request)
    if payload.dataset not in DATASETS:raise HTTPException(422,'Unknown dataset')
    p=_eval_root()/payload.dataset
    if not p.is_file():raise HTTPException(404,'Dataset not found')
    with SessionLocal() as db:
        if _repo(db,payload.repo_id).status!='indexed':raise HTTPException(409,'Repository not indexed')
    return begin_evaluation(payload.repo_id,p,payload.limit)
