from pydantic import BaseModel, Field, HttpUrl


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


class SourceResponse(BaseModel):
    label: str
    file_path: str
    symbol_name: str | None
    start_line: int
    end_line: int
    distance: float


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceResponse]