from pydantic import BaseModel, Field, HttpUrl
from typing import Literal


class IndexRepositoryRequest(BaseModel):
    url: HttpUrl


class RepositoryResponse(BaseModel):
    id: str
    url: str
    commit_sha: str
    status: str


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    top_k: int = Field(default=8, ge=1, le=20)
    retrieval_mode: Literal[
        "dense",
        "graph",
        "keyword",
        "hybrid",
        "hybrid_rerank",
        "hybrid_graph",
        "hybrid_graph_rerank",
        "agent",
    ] = "hybrid"
    docs_policy: Literal["auto", "always", "never"] = "auto"


class SourceResponse(BaseModel):
    label: str
    file_path: str
    symbol_name: str | None
    start_line: int
    end_line: int
    distance: float | None = None
    origin: str
    channels: list[str] = Field(default_factory=list)
    fusion_score: float | None = None
    rerank_score: float | None = None


class DocumentationSource(BaseModel):
    label: str
    library: str
    topic: str
    title: str
    url: str


class AskResponse(BaseModel):
    answer: str
    trace_id: str | None = None
    status: str = "answered"
    cached: bool = False
    sources: list[SourceResponse]
    docs_sources: list[DocumentationSource] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
