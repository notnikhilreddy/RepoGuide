"""Deterministic exact-symbol boost for identifier questions."""
from __future__ import annotations
import re
from sqlalchemy import select
from sqlalchemy.orm import Session
from repoguide.models import CodeSymbol, Chunk
from repoguide.hybrid import SearchHit
from repoguide.telemetry import span, record


def exact_symbols(session: Session, repo_id: str, question: str, limit: int = 4) -> list[SearchHit]:
    identifiers=re.findall(r'`([A-Za-z_]\w{2,80})`',question)
    if not identifiers:
        return []
    with span('retrieval.exact_symbol','RETRIEVER',{'identifiers':identifiers}) as sp:
        symbols=session.scalars(select(CodeSymbol).where(CodeSymbol.repo_id==repo_id,CodeSymbol.name.in_(identifiers)).limit(30)).all()
        found=[];seen=set()
        for sym in symbols:
            chunks=session.scalars(select(Chunk).where(Chunk.repo_id==repo_id,Chunk.file_path==sym.file_path,Chunk.start_line<=sym.start_line,Chunk.end_line>=sym.start_line).limit(3)).all()
            for chunk in chunks:
                if chunk.id not in seen:
                    found.append(SearchHit(chunk,'exact',channels=('exact',)))
                    seen.add(chunk.id)
                if len(found)>=limit:
                    break
            if len(found)>=limit:break
        record(sp, {'matches':[x.chunk.file_path for x in found]}, matched_symbols=len(symbols))
        return found
