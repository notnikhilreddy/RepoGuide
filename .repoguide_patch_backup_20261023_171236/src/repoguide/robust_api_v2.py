"""New endpoints; do not replace the M4 /ask endpoint during rollout."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from repoguide.answers_v2 import AnswerResult
from repoguide.db import SessionLocal
from repoguide.models import Repository
from repoguide.robust_v2 import robust_answer, stream_robust_answer

router = APIRouter(tags=["Milestone 5"])


class RobustRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    top_k: int = Field(default=8, ge=1, le=20)
    docs_policy: Literal["auto", "always", "never"] = "auto"


def check_repository(repo_id: str) -> None:
    with SessionLocal() as session:
        record = session.scalar(select(Repository).where(Repository.id == repo_id))
        if record is None:
            raise HTTPException(status_code=404, detail="Repository not found")
        if record.status != "indexed":
            raise HTTPException(status_code=409, detail="Repository is not indexed")


@router.post("/repositories/{repo_id}/ask/robust", response_model=AnswerResult)
def ask_robust(repo_id: str, request: RobustRequest):
    check_repository(repo_id)
    return robust_answer(repo_id=repo_id, question=request.question,
                         top_k=request.top_k, docs_policy=request.docs_policy)


@router.post("/repositories/{repo_id}/ask/stream")
def ask_stream(repo_id: str, request: RobustRequest):
    check_repository(repo_id)
    return StreamingResponse(
        stream_robust_answer(repo_id=repo_id, question=request.question,
                             top_k=request.top_k, docs_policy=request.docs_policy),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
