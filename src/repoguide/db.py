from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from repoguide.config import settings


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=2,
    max_overflow=1,
    pool_timeout=10,
    pool_recycle=300,
)

from repoguide.sql_observability import instrument_engine
instrument_engine(engine)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def get_db():
    with SessionLocal() as session:
        yield session
