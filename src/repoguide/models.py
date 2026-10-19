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

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=new_id
    )

    url: Mapped[str] = mapped_column(Text, nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="indexing"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "url", "commit_sha",
            name="uq_repository_url_commit",
        ),
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=new_id
    )

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
