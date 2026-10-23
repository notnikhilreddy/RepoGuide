"""One API adapter over the unified pipeline, including trace-linked feedback."""
from __future__ import annotations

from typing import Literal
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from repoguide.answers import AnswerResult
from repoguide.db import SessionLocal
from repoguide.models import Repository
from repoguide.pipeline import answer, stream_answer
from repoguide.telemetry import feedback, span, record

router=APIRouter(tags=['Answers & evaluation'])

class Query(BaseModel):
    question:str=Field(min_length=3,max_length=2000)
    top_k:int=Field(default=8,ge=1,le=20)
    docs_policy:Literal['never','auto','always']='auto'
    retrieval_mode:Literal['dense','graph','keyword','hybrid','hybrid_rerank','hybrid_graph','hybrid_graph_rerank']='hybrid'
    answer_depth:Literal['auto','concise','standard','detailed']='auto'

class FeedbackRequest(BaseModel):
    trace_id:str=Field(min_length=5,max_length=160)
    rating: int=Field(ge=1,le=5)
    category:Literal['correct','incorrect','incomplete','citation','other']='other'
    comment:str=Field(default='',max_length=1000)


def check_repo(repo_id:str):
    with SessionLocal() as session:
        record_=session.scalar(select(Repository).where(Repository.id==repo_id))
        if record_ is None: raise HTTPException(404,'Repository not found')
        if record_.status!='indexed': raise HTTPException(409,'Repository not indexed')

@router.post('/repositories/{repo_id}/ask/robust',response_model=AnswerResult)
def ask_robust(repo_id:str,request:Query):
    check_repo(repo_id)
    return answer(repo_id=repo_id,**request.model_dump())

@router.post('/repositories/{repo_id}/ask/stream')
def ask_stream(repo_id:str,request:Query):
    check_repo(repo_id)
    return StreamingResponse(stream_answer(repo_id=repo_id,**request.model_dump()),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

@router.post('/feedback')
def submit_feedback(request:FeedbackRequest):
    # Local single-user development endpoint. Require authentication + trace
    # ownership checks before exposing to untrusted users in production.
    with span('feedback.submit','TOOL',request.model_dump(exclude={'comment'})) as sp:
        try:
            success=feedback(request.trace_id,'user_rating',request.rating,request.category + ': ' + request.comment,human=True)
        except Exception:
            raise HTTPException(status_code=503,detail='Feedback backend unavailable') from None
        record(sp,{'recorded':success})
        if not success: raise HTTPException(503,'Feedback tracking disabled')
        return {'recorded':True,'trace_id':request.trace_id}
