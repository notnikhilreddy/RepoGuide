from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from repoguide.db import get_db
from repoguide.git_utils import parse_github_url
from repoguide.indexer import index_repository
from repoguide.models import Repository
from repoguide.rag import answer_question
from repoguide.schemas import (
    AskRequest,
    AskResponse,
    IndexRepositoryRequest,
    RepositoryResponse,
)
from repoguide.graph_api import router as graph_router
from repoguide.agent import answer_with_agent
from repoguide.robust_api_v2 import router as robust_router


app = FastAPI(
    title="RepoGuide API",
    description="Understand GitHub repositories using grounded RAG.",
    version="0.1.0",
)
app.include_router(graph_router)
app.include_router(robust_router)


SessionDep = Annotated[Session, Depends(get_db)]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post(
    "/repositories/index",
    response_model=RepositoryResponse,
)
def index_repo(
    request: IndexRepositoryRequest,
    session: SessionDep,
):
    try:
        parse_github_url(str(request.url))

        repo = index_repository(
            str(request.url),
            session,
        )

    except (ValueError, RuntimeError) as exc:
        session.rollback()
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return RepositoryResponse(
        id=repo.id,
        url=repo.url,
        commit_sha=repo.commit_sha,
        status=repo.status,
    )


@app.get(
    "/repositories/{repo_id}",
    response_model=RepositoryResponse,
)
def get_repository(
    repo_id: str,
    session: SessionDep,
):
    repo = session.scalar(select(Repository).where(Repository.id == repo_id))

    if repo is None:
        raise HTTPException(
            status_code=404,
            detail="Repository not found",
        )

    return RepositoryResponse(
        id=repo.id,
        url=repo.url,
        commit_sha=repo.commit_sha,
        status=repo.status,
    )


@app.post(
    "/repositories/{repo_id}/ask",
    response_model=AskResponse,
)
def ask_repository(
    repo_id: str,
    request: AskRequest,
    session: SessionDep,
):
    repo = session.scalar(select(Repository).where(Repository.id == repo_id))

    if repo is None:
        raise HTTPException(
            status_code=404,
            detail="Repository not found",
        )

    if repo.status != "indexed":
        raise HTTPException(
            status_code=409,
            detail="Repository is not ready",
        )

    if request.retrieval_mode == "agent":
        result = answer_with_agent(
            repo_id=repo_id,
            question=request.question,
            top_k=request.top_k,
            docs_policy=request.docs_policy,
        )
    else:
        result = answer_question(
            session=session,
            repo_id=repo_id,
            question=request.question,
            top_k=request.top_k,
            retrieval_mode=request.retrieval_mode,
        )

    return AskResponse(**result)

