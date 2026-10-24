from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from repoguide.db import SessionLocal
from repoguide.models import CodeEdge, CodeSymbol, RepoDependency, Repository

router = APIRouter()


@router.get("/repositories/{repo_id}/symbols")
def get_symbols(repo_id: str, name: str = "", limit: int = Query(50, ge=1, le=200)):
    with SessionLocal() as db:
        if not db.get(Repository, repo_id):
            raise HTTPException(404, "Repository not found")
        q = select(CodeSymbol).where(CodeSymbol.repo_id == repo_id)
        if name:
            q = q.where(
                CodeSymbol.name.ilike(
                    f"%{name.replace('%', r'\%').replace('_', r'\_')}%", escape="\\"
                )
            )
        rows = db.scalars(
            q.order_by(CodeSymbol.file_path, CodeSymbol.start_line).limit(limit)
        ).all()
        return [
            {
                "id": s.id,
                "name": s.name,
                "qualified_name": s.qualified_name,
                "kind": s.kind,
                "language": s.language,
                "file_path": s.file_path,
                "start_line": s.start_line,
                "end_line": s.end_line,
            }
            for s in rows
        ]


@router.get("/repositories/{repo_id}/graph")
def get_graph(repo_id: str, limit: int = Query(500, ge=1, le=2000)):
    with SessionLocal() as db:
        if not db.get(Repository, repo_id):
            raise HTTPException(404, "Repository not found")
        edges = db.scalars(
            select(CodeEdge)
            .where(CodeEdge.repo_id == repo_id)
            .order_by(CodeEdge.kind, CodeEdge.line)
            .limit(limit)
        ).all()
        ids = {e.source_symbol_id for e in edges} | {
            e.target_symbol_id for e in edges if e.target_symbol_id
        }
        nodes = (
            db.scalars(select(CodeSymbol).where(CodeSymbol.id.in_(ids))).all()
            if ids
            else []
        )
        return {
            "nodes": [
                {
                    "id": s.id,
                    "label": s.qualified_name,
                    "file_path": s.file_path,
                    "kind": s.kind,
                    "language": s.language,
                    "start_line": s.start_line,
                    "end_line": s.end_line,
                }
                for s in nodes
            ],
            "edges": [
                {
                    "id": e.id,
                    "source": e.source_symbol_id,
                    "target": e.target_symbol_id,
                    "target_name": e.target_name,
                    "kind": e.kind,
                    "line": e.line,
                    "resolved": e.target_symbol_id is not None,
                }
                for e in edges
            ],
        }


@router.get("/repositories/{repo_id}/dependencies")
def get_dependencies(repo_id: str):
    with SessionLocal() as db:
        if not db.get(Repository, repo_id):
            raise HTTPException(404, "Repository not found")
        rows = db.scalars(
            select(RepoDependency)
            .where(RepoDependency.repo_id == repo_id)
            .order_by(RepoDependency.name)
        ).all()
        return [
            {"name": x.name, "spec": x.spec, "manifest": x.manifest, "group": x.group}
            for x in rows
        ]
