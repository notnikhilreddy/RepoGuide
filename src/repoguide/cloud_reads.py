"""Bounded, read-only Neon browsing. No ORM, API framework, or ML imports."""

from __future__ import annotations

import os
from contextlib import contextmanager
from urllib.parse import urlparse

_connection = None
TABLES = {
    "chunks": "chunks",
    "symbols": "code_symbols",
    "edges": "code_edges",
    "dependencies": "repo_dependencies",
    "files": "source_files",
}


@contextmanager
def database():
    import psycopg
    from psycopg.rows import dict_row

    global _connection
    for attempt in range(2):
        ready = False
        try:
            if _connection is None or _connection.closed:
                url = os.environ["READ_DATABASE_URL"].replace(
                    "postgresql+psycopg://", "postgresql://"
                )
                _connection = psycopg.connect(
                    url,
                    sslmode="require",
                    connect_timeout=4,
                    row_factory=dict_row,
                    application_name="repoguide-read-api",
                )
            with _connection.transaction():
                _connection.execute("SET TRANSACTION READ ONLY")
                _connection.execute("SET LOCAL statement_timeout = '2500ms'")
                ready = True
                yield _connection
            return
        except Exception as exc:
            if _connection is not None:
                _connection.close()
            _connection = None
            # Neon can close an idle pooled connection while Lambda is frozen.
            # Reconnect once before handing it to application code. Never
            # replay a request's SQL or any work already executed after yield.
            if (
                not ready
                and attempt == 0
                and isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError))
            ):
                continue
            raise


def counts_sql(alias="r"):
    # Identifiers are fixed constants, never request data.
    return ",".join(
        f"(SELECT count(*) FROM {table} t WHERE t.repo_id={alias}.id) AS {key}"
        for key, table in TABLES.items()
    )


def repository(db, repo_id):
    row = db.execute("SELECT * FROM repositories WHERE id=%s", (repo_id,)).fetchone()
    if row is None:
        raise LookupError("Repository not found")
    return row


def bounded(query, key, default, maximum):
    value = int(query.get(key, default))
    if value < 0 or value > maximum or (key == "limit" and value == 0):
        raise ValueError(f"Invalid {key}")
    return value


def path_check(path):
    if (
        not path
        or len(path) > 1000
        or path.startswith("/")
        or any(p in {"..", ".", ""} for p in path.split("/"))
        or "\\" in path
        or "\x00" in path
    ):
        raise ValueError("Invalid path")
    return path


def browse(path, query, allowed_ids=None):
    with database() as db:
        if path == "/ready":
            db.execute("SELECT 1").fetchone()
            return {"ready": True, "database": "available"}
        if path == "/api/ui/repositories":
            limit = bounded(query, "limit", 30, 100)
            offset = bounded(query, "offset", 0, 100000)
            rows = db.execute(
                f"SELECT r.*, {counts_sql()} FROM repositories r "
                + ("WHERE r.id=ANY(%s) " if allowed_ids is not None else "")
                + "ORDER BY created_at DESC,id LIMIT %s OFFSET %s",
                (
                    (list(allowed_ids), limit, offset)
                    if allowed_ids is not None
                    else (limit, offset)
                ),
            ).fetchall()
            for row in rows:
                row["counts"] = {k: row.pop(k) for k in TABLES}
                row["name"] = urlparse(row["url"]).path.strip("/")
            return rows
        parts = path.strip("/").split("/")
        if path.startswith("/api/ui/repositories/"):
            if len(parts) != 5:
                raise LookupError("Unknown route")
            repo_id, action = parts[3:]
        elif path.startswith("/repositories/") and len(parts) == 3:
            repo_id, action = parts[1:]
        else:
            raise LookupError("Unknown route")
        repo = repository(db, repo_id)
        repo.pop("owner_sub", None)
        if action == "overview":
            from repoguide.repository_views import overview_details

            totals = db.execute(
                f"SELECT {counts_sql()} FROM repositories r WHERE id=%s", (repo_id,)
            ).fetchone()
            languages = db.execute(
                "SELECT language,count(*) AS n FROM code_symbols WHERE repo_id=%s GROUP BY language",
                (repo_id,),
            ).fetchall()
            edges = db.execute(
                "SELECT kind,count(*) AS n FROM code_edges WHERE repo_id=%s GROUP BY kind",
                (repo_id,),
            ).fetchall()
            return {
                **repo,
                "counts": totals,
                "languages": {r["language"]: r["n"] for r in languages},
                "edge_types": {r["kind"]: r["n"] for r in edges},
                "has_exact_sources": bool(totals["files"]),
                **overview_details(db, repo_id, totals["files"]),
            }
        if action == "files":
            limit = bounded(query, "limit", 2200, 2200)
            offset = bounded(query, "offset", 0, 100000)
            return db.execute(
                "WITH indexed AS (SELECT file_path AS path,count(*) AS chunks FROM chunks WHERE repo_id=%s GROUP BY file_path) "
                "SELECT coalesce(s.path,c.path) AS path,s.byte_count AS bytes,(s.path IS NOT NULL) AS exact,coalesce(c.chunks,0) AS chunks "
                "FROM (SELECT path,byte_count FROM source_files WHERE repo_id=%s) s FULL JOIN indexed c USING(path) "
                "ORDER BY path LIMIT %s OFFSET %s",
                (repo_id, repo_id, limit, offset),
            ).fetchall()
        if action == "file":
            file_path = path_check(query.get("path", ""))
            row = db.execute(
                "SELECT content,byte_count FROM source_files WHERE repo_id=%s AND path=%s AND octet_length(content)<=300000",
                (repo_id, file_path),
            ).fetchone()
            if row:
                if row["content"].count("\n") >= 4000:
                    raise ValueError("File exceeds the 4000-line browsing limit")
                return {
                    "path": file_path,
                    **row,
                    "partial": False,
                    "lines": row["content"].count("\n") + 1,
                }
            if db.execute(
                "SELECT 1 FROM source_files WHERE repo_id=%s AND path=%s",
                (repo_id, file_path),
            ).fetchone():
                raise ValueError("File exceeds the 300 KB browsing limit")
            chunks = db.execute(
                "SELECT start_line,end_line,left(content,300000) AS content FROM chunks WHERE repo_id=%s AND file_path=%s ORDER BY start_line,end_line LIMIT 500",
                (repo_id, file_path),
            ).fetchall()
            if not chunks:
                raise LookupError("File not in indexed repository")
            lines = {}
            for chunk in chunks:
                for pos, text in enumerate(
                    chunk["content"].splitlines(), chunk["start_line"]
                ):
                    if pos <= 4000:
                        lines.setdefault(pos, text)
            content = "\n".join(
                lines.get(i, "") for i in range(1, max(lines, default=0) + 1)
            )[:300000]
            return {
                "path": file_path,
                "content": content,
                "partial": True,
                "lines": content.count("\n") + 1,
                "byte_count": None,
                "note": "Reconstructed from indexed chunks; missing lines may be blank. Reindex for exact source.",
            }
        if action in {"symbols", "symbols-in-file"}:
            args = [repo_id]
            where = "repo_id=%s"
            if action == "symbols-in-file":
                where += " AND file_path=%s"
                args.append(path_check(query.get("path", "")))
            elif query.get("name"):
                where += " AND position(lower(%s) in lower(name))>0"
                args.append(query["name"][:200])
            args += [
                bounded(query, "limit", 200, 250),
                bounded(query, "offset", 0, 100000),
            ]
            return db.execute(
                "SELECT id,name,qualified_name,kind,language,file_path,start_line,end_line FROM code_symbols WHERE "
                + where
                + " ORDER BY file_path,start_line,id LIMIT %s OFFSET %s",
                args,
            ).fetchall()
        if action == "dependencies":
            return db.execute(
                'SELECT name,spec,manifest,"group" FROM repo_dependencies WHERE repo_id=%s ORDER BY name,id LIMIT %s OFFSET %s',
                (
                    repo_id,
                    bounded(query, "limit", 2000, 2000),
                    bounded(query, "offset", 0, 100000),
                ),
            ).fetchall()
        if action == "graph":
            edges = db.execute(
                "SELECT id,source_symbol_id AS source,target_symbol_id AS target,target_name,kind,line,(target_symbol_id IS NOT NULL) AS resolved FROM code_edges WHERE repo_id=%s ORDER BY kind,line,id LIMIT %s OFFSET %s",
                (
                    repo_id,
                    bounded(query, "limit", 500, 2000),
                    bounded(query, "offset", 0, 100000),
                ),
            ).fetchall()
            ids = list(
                {e["source"] for e in edges}
                | {e["target"] for e in edges if e["target"]}
            )
            nodes = (
                db.execute(
                    "SELECT id,qualified_name AS label,file_path,kind,language,start_line,end_line FROM code_symbols WHERE repo_id=%s AND id=ANY(%s)",
                    (repo_id, ids),
                ).fetchall()
                if ids
                else []
            )
            return {"nodes": nodes, "edges": edges}
        raise LookupError("Unknown route")
