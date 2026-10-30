import uuid
from datetime import datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from repoguide.config import settings
from repoguide.db import Base


def new_id() -> str:
    return str(uuid.uuid4())


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)

    url: Mapped[str] = mapped_column(Text, nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="indexing")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "url",
            "commit_sha",
            name="uq_repository_url_commit",
        ),
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)

    repo_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    symbol_name: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    start_line: Mapped[int] = mapped_column(nullable=False)
    end_line: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    embedding: Mapped[list[float]] = mapped_column(
        VECTOR(settings.embedding_dim),
        nullable=False,
    )


class CodeSymbol(Base):
    __tablename__ = "code_symbols"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    repo_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        index=True,
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    qualified_name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    start_line: Mapped[int] = mapped_column(nullable=False)
    end_line: Mapped[int] = mapped_column(nullable=False)


class CodeEdge(Base):
    __tablename__ = "code_edges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    repo_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        index=True,
    )
    source_symbol_id: Mapped[str] = mapped_column(
        ForeignKey("code_symbols.id", ondelete="CASCADE"),
        index=True,
    )
    target_symbol_id: Mapped[str | None] = mapped_column(
        ForeignKey("code_symbols.id", ondelete="SET NULL"),
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    target_name: Mapped[str] = mapped_column(Text, nullable=False)
    line: Mapped[int] = mapped_column(nullable=False)


class RepoDependency(Base):
    __tablename__ = "repo_dependencies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    repo_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    spec: Mapped[str] = mapped_column(Text, nullable=False)
    manifest: Mapped[str] = mapped_column(Text, nullable=False)
    group: Mapped[str] = mapped_column(String(40), nullable=False)


class SourceFile(Base):
    """Exact read-only source snapshot for Monaco, keyed by indexed commit."""

    __tablename__ = "source_files"
    repo_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    path: Mapped[str] = mapped_column(Text, primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    byte_count: Mapped[int] = mapped_column(nullable=False)
