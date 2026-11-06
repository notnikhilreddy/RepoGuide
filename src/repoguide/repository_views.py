"""Grounded, bounded repository read models. No inference or external calls."""

from __future__ import annotations

from collections import Counter

from repoguide.cloud_reads import path_check, repository


def architecture(db, repo_id, query):
    scope = str(query.get("scope", "")).strip("/")
    if scope and scope != "@root":
        path_check(scope)
    files = db.execute(
        "SELECT s.path,coalesce(c.n,0) AS chunks,coalesce(y.n,0) AS symbols FROM source_files s "
        "LEFT JOIN (SELECT file_path,count(*) n FROM chunks WHERE repo_id=%s GROUP BY file_path) c ON c.file_path=s.path "
        "LEFT JOIN (SELECT file_path,count(*) n FROM code_symbols WHERE repo_id=%s GROUP BY file_path) y ON y.file_path=s.path "
        "WHERE s.repo_id=%s ORDER BY s.path LIMIT 2201",
        (repo_id, repo_id, repo_id),
    ).fetchall()
    if not files:
        files = db.execute(
            "SELECT file_path AS path,count(*) AS chunks,0 AS symbols FROM chunks WHERE repo_id=%s GROUP BY file_path ORDER BY file_path LIMIT 2201",
            (repo_id,),
        ).fetchall()
    groups, group_for_file = {}, {}
    for row in files[:2200]:
        path = row["path"]
        if scope == "@root":
            if "/" in path:
                continue
            child, is_file = path, True
        elif scope:
            if not path.startswith(scope + "/"):
                continue
            relative = path[len(scope) + 1 :]
            child, is_file = scope + "/" + relative.split("/")[0], "/" not in relative
        elif "/" in path:
            child, is_file = path.split("/")[0], False
        else:
            child, is_file = "@root", False
        node = groups.setdefault(
            child,
            {
                "id": child,
                "label": "Repository files"
                if child == "@root"
                else child.rsplit("/", 1)[-1],
                "scope": child,
                "kind": "file" if is_file else "module",
                "files": 0,
                "symbols": 0,
                "preview_path": path,
            },
        )
        node["files"] += 1
        node["symbols"] += row["symbols"]
        group_for_file[path] = child
    relations = db.execute(
        "SELECT s.file_path AS source,t.file_path AS target,e.kind,count(*) AS n FROM code_edges e "
        "JOIN code_symbols s ON s.id=e.source_symbol_id AND s.repo_id=e.repo_id JOIN code_symbols t ON t.id=e.target_symbol_id AND t.repo_id=e.repo_id "
        "WHERE e.repo_id=%s AND e.kind<>'contains' AND s.file_path<>t.file_path "
        "GROUP BY s.file_path,t.file_path,e.kind ORDER BY n DESC,s.file_path,t.file_path LIMIT 10001",
        (repo_id,),
    ).fetchall()
    edges = Counter()
    for row in relations[:10000]:
        source, target = (
            group_for_file.get(row["source"]),
            group_for_file.get(row["target"]),
        )
        if source and target and source != target:
            edges[(source, target, row["kind"])] += row["n"]
    search = str(query.get("q", ""))[:200].casefold()
    matches = [
        node
        for node in groups.values()
        if search in node["scope"].casefold() or search in node["label"].casefold()
    ]
    limit = max(1, min(60, int(query.get("limit", 12 if not scope else 40))))
    nodes = sorted(
        matches, key=lambda n: (-n["files"], n["kind"] == "file", n["label"].casefold())
    )[:limit]
    visible = {n["id"] for n in nodes}
    return {
        "scope": scope,
        "nodes": nodes,
        "edges": [
            {"source": s, "target": t, "kind": k, "count": n}
            for (s, t, k), n in sorted(edges.items())
            if s in visible and t in visible
        ],
        "truncated": len(matches) > limit
        or len(files) > 2200
        or len(relations) > 10000,
        "total_nodes": len(matches),
    }


def health(db, repo_id, grant):
    repo = repository(db, repo_id)
    metadata = repo.get("index_metadata") or {}
    return {
        "commit_sha": repo["commit_sha"],
        "branch": grant.get("monitored_branch"),
        "status": repo["status"],
        "indexed_at": repo["created_at"],
        "diagnostics_available": bool(metadata),
        **metadata,
        "note": None
        if metadata
        else "This older index has no detailed ingestion report. Update it to collect diagnostics.",
    }


def overview_details(db, repo_id, total_files=None):
    graph = architecture(db, repo_id, {"limit": 60})
    modules = sorted(graph["nodes"], key=lambda n: -n["files"])[:6]
    dependencies = db.execute(
        'SELECT name,spec,manifest,"group" FROM repo_dependencies WHERE repo_id=%s ORDER BY name LIMIT 80',
        (repo_id,),
    ).fetchall()
    entrypoints = db.execute(
        "SELECT DISTINCT file_path,name,start_line FROM code_symbols WHERE repo_id=%s AND (name='main' OR name='__main__') ORDER BY file_path,start_line LIMIT 10",
        (repo_id,),
    ).fetchall()
    questions = []
    if modules:
        questions.append(
            "Explain the responsibilities of "
            + modules[0]["scope"]
            + " using the indexed source."
        )
    if graph["edges"]:
        edge = max(graph["edges"], key=lambda e: e["count"])
        questions.append(
            f"Trace the {edge['kind']} relationships from {edge['source']} to {edge['target']} across files."
        )
    if dependencies:
        questions.append(
            "Where is "
            + dependencies[0]["name"]
            + " used in this repository, and what does the code use it for?"
        )
    return {
        "modules": modules,
        "entrypoints": entrypoints,
        "tech_stack": dependencies,
        "suggested_questions": questions,
        "summary": f"The indexed source contains {total_files if total_files is not None else sum(n['files'] for n in graph['nodes'])} files grouped into {graph['total_nodes']} top-level modules and file groups. Relationships below come from parsed source symbols.",
    }
