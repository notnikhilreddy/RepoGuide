"""RepoGuide API: one unified RAG/agent execution path, two response forms."""

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from repoguide.api import router as answer_router
from repoguide.db import get_db
from repoguide.git_utils import parse_github_url
from repoguide.graph_api import router as graph_router
from repoguide.indexer import index_repository
from repoguide.models import Repository
from repoguide.pipeline import answer
from repoguide.schemas import (
    AskRequest,
    AskResponse,
    IndexRepositoryRequest,
    RepositoryResponse,
)
from repoguide.telemetry import record, setup_mlflow, span
from repoguide.ui_api import router as ui_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_mlflow()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="RepoGuide API",
    description="Versioned, evidence-grounded repository assistant",
    version="0.6.0",
)
app.include_router(graph_router)
app.include_router(answer_router)
app.include_router(ui_router)
SessionDep = Annotated[Session, Depends(get_db)]


@app.middleware("http")
async def cloud_metrics(request: Request, call_next):
    import time

    from repoguide.cloud_observability import emit_request

    start = time.monotonic()
    try:
        response = await call_next(request)
        emit_request(
            request.method,
            request.url.path,
            response.status_code,
            (time.monotonic() - start) * 1000,
        )
        return response
    except Exception:
        emit_request(
            request.method, request.url.path, 500, (time.monotonic() - start) * 1000
        )
        raise


@app.middleware("http")
async def cloud_request_protection(request: Request, call_next):
    import os

    if os.getenv("REPOGUIDE_CLOUD_MODE", "").lower() == "true":
        # The JWT signature and audience are enforced by the API Gateway authorizer.
        # Browser-controlled headers must NEVER substitute for gateway claims.
        if request.url.path == "/repositories/index":
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=403, content={"detail": "Use durable index jobs"}
            )
        if request.method == "POST" and (
            "/ask" in request.url.path or request.url.path == "/feedback"
        ):
            from fastapi.responses import JSONResponse

            from repoguide.cloud_guard import enforce_request_budget

            try:
                enforce_request_budget(request)
            except HTTPException as exc:
                return JSONResponse(
                    status_code=exc.status_code, content={"detail": exc.detail}
                )
    return await call_next(request)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/repositories/index", response_model=RepositoryResponse)
def index_repo(request: IndexRepositoryRequest, session: SessionDep):
    with span("http.index_repository", "CHAIN", {"url": str(request.url)}) as sp:
        try:
            parse_github_url(str(request.url))
            repo = index_repository(str(request.url), session)
        except (ValueError, RuntimeError) as exc:
            session.rollback()
            raise HTTPException(400, str(exc)) from exc
        result = RepositoryResponse(
            id=repo.id, url=repo.url, commit_sha=repo.commit_sha, status=repo.status
        )
        record(sp, result.model_dump(), commit_sha=repo.commit_sha)
        return result


@app.get("/repositories/{repo_id}", response_model=RepositoryResponse)
def get_repository(repo_id: str, session: SessionDep):
    with span("db.repository_lookup", "RETRIEVER", {"repo_id": repo_id}) as sp:
        repo = session.scalar(select(Repository).where(Repository.id == repo_id))
        if repo is None:
            raise HTTPException(404, "Repository not found")
        result = RepositoryResponse(
            id=repo.id, url=repo.url, commit_sha=repo.commit_sha, status=repo.status
        )
        record(sp, result.model_dump())
        return result


@app.post("/repositories/{repo_id}/ask", response_model=AskResponse)
def ask_repository(repo_id: str, request: AskRequest, session: SessionDep):
    repo = session.scalar(select(Repository).where(Repository.id == repo_id))
    if repo is None:
        raise HTTPException(404, "Repository not found")
    if repo.status != "indexed":
        raise HTTPException(409, "Repository not indexed")
    result = answer(
        repo_id=repo_id,
        question=request.question,
        top_k=request.top_k,
        docs_policy=request.docs_policy,
        retrieval_mode="hybrid"
        if request.retrieval_mode == "agent"
        else request.retrieval_mode,
    )
    return AskResponse(
        answer=result.answer,
        sources=result.sources,
        docs_sources=result.docs_sources,
        trace=result.trace,
        trace_id=result.trace_id,
        status=result.status,
        cached=result.cached,
    )
