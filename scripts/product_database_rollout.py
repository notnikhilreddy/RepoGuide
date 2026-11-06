"""Audit, back up/restore, or migrate the existing RepoGuide database and grants.

Only --apply mutates production. It requires the exact verified private backup,
uses the existing administrator identity, and preserves original source rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

import boto3
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from update_runtime_settings import load_settings

ROOT = Path(__file__).resolve().parents[1]
TABLES = [
    "repositories",
    "chunks",
    "code_symbols",
    "code_edges",
    "repo_dependencies",
    "source_files",
]
PROOF = ROOT / ".artifacts/product-database-backup.json"
BACKUP = ROOT / ".artifacts/private/neon-before-product.dump"


def outputs():
    result = json.loads(
        subprocess.check_output(
            ["terraform", "-chdir=" + str(ROOT / "infra/terraform"), "output", "-json"],
            text=True,
        )
    )
    return {k: v["value"] for k, v in result.items()}


def snapshot(connection, ids=None):
    if ids is None:
        ids = [
            r[0] for r in connection.execute("SELECT id FROM repositories ORDER BY id")
        ]
    result = {}
    for table in TABLES:
        key = "id" if table == "repositories" else "repo_id"
        expression = (
            "to_jsonb(t)-'owner_sub'-'parent_repo_id'-'index_metadata'"
            if table == "repositories"
            else "to_jsonb(t)"
        )
        query = sql.SQL(
            'SELECT ({})::text FROM {} t WHERE {}=ANY(%s) ORDER BY ({})::text COLLATE "C"'
        ).format(
            sql.SQL(expression),
            sql.Identifier(table),
            sql.Identifier(key),
            sql.SQL(expression),
        )
        digest = hashlib.sha256()
        count = 0
        for (row,) in connection.execute(query, (list(ids),)):
            digest.update(row.encode() + b"\n")
            count += 1
        result[table] = {"rows": count, "sha256": digest.hexdigest()}
    return {"repository_ids": list(ids), "tables": result}


def database_url():
    return load_settings(ROOT / ".env.deploy")["DATABASE_URL"].replace(
        "postgresql+psycopg://", "postgresql://"
    )


def readonly(url):
    return psycopg.connect(
        url,
        connect_timeout=10,
        options="-c default_transaction_read_only=on -c timezone=UTC",
    )


def audit(session, out, url):
    ecs = session.client("ecs")
    lamb = session.client("lambda")
    services = ecs.describe_services(
        cluster=out["ecs_cluster"], services=list(out["ecs_services"].values())
    )["services"]
    workers = {}
    for service in services:
        task = ecs.describe_task_definition(taskDefinition=service["taskDefinition"])[
            "taskDefinition"
        ]
        kind = next(
            k for k, v in out["ecs_services"].items() if v == service["serviceName"]
        )
        workers[kind] = {
            k: service[k]
            for k in ["desiredCount", "runningCount", "pendingCount", "taskDefinition"]
        }
        workers[kind]["image"] = task["containerDefinitions"][0]["image"]
        workers[kind]["cpu"] = task["cpu"]
        workers[kind]["memory"] = task["memory"]
    api = lamb.get_function_configuration(FunctionName=out["api_function"])
    with readonly(url) as db:
        data = snapshot(db)
        revision = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        size = db.execute("SELECT pg_database_size(current_database())").fetchone()[0]
    report = {
        "observed_at": int(time.time()),
        "account": session.client("sts").get_caller_identity()["Account"],
        "api_url": out["api_url"],
        "release_id": api["Environment"]["Variables"]["REPOGUIDE_RELEASE"],
        "api_code_sha256": api["CodeSha256"],
        "workers": workers,
        "database": {"schema_revision": revision, "bytes": size, **data},
        "outputs": out,
    }
    path = ROOT / ".artifacts/product-cloud-before.json"
    path.write_text(json.dumps(report, indent=2))
    print(
        json.dumps(
            {
                "audit": True,
                "release_id": report["release_id"],
                "workers": {
                    k: {
                        x: v[x]
                        for x in ["desiredCount", "runningCount", "pendingCount"]
                    }
                    for k, v in workers.items()
                },
                "schema_revision": revision,
                "repositories": len(data["repository_ids"]),
            }
        )
    )
    return report


def backup(url):
    if PROOF.exists() or BACKUP.exists():
        raise ValueError(
            "A product backup already exists; preserve and verify it instead of overwriting"
        )
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    parts = urlsplit(url)
    env = {
        **os.environ,
        "PGHOST": (parts.hostname or "").replace("-pooler.", "."),
        "PGPORT": str(parts.port or 5432),
        "PGUSER": unquote(parts.username or ""),
        "PGPASSWORD": unquote(parts.password or ""),
        "PGDATABASE": parts.path.lstrip("/"),
        "PGSSLMODE": "require",
        "PGCONNECT_TIMEOUT": "10",
    }
    binary = shutil.which("pg_dump")
    if not binary:
        candidate = Path("/opt/homebrew/opt/postgresql@18/bin/pg_dump")
        binary = str(candidate) if candidate.exists() else None
    dump_command = (
        [binary]
        if binary
        else [
            "docker",
            "exec",
            *[
                arg
                for key in [
                    "PGHOST",
                    "PGPORT",
                    "PGUSER",
                    "PGPASSWORD",
                    "PGDATABASE",
                    "PGSSLMODE",
                    "PGCONNECT_TIMEOUT",
                ]
                for arg in ["-e", key]
            ],
            "repoguide-validation",
            "pg_dump",
        ]
    )
    with readonly(url) as db:
        before = snapshot(db)
        schema = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    descriptor = os.open(BACKUP, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        result = subprocess.run(
            [*dump_command, "--format=custom", "--no-owner", "--no-acl"],
            env=env,
            stdout=stream,
            stderr=subprocess.PIPE,
        )
    if result.returncode:
        raise RuntimeError("Database backup failed; original database was not changed")
    if BACKUP.read_bytes()[:5] != b"PGDMP":
        raise ValueError("Backup format is invalid")
    name = "rg_product_backup_" + uuid.uuid4().hex[:12]
    local = "postgresql://repoguide:repoguide@127.0.0.1:55432/postgres?sslmode=require"
    with psycopg.connect(local, autocommit=True) as db:
        db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    with BACKUP.open("rb") as stream:
        restored = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                "repoguide-validation",
                "pg_restore",
                "--exit-on-error",
                "--no-owner",
                "--no-acl",
                "-U",
                "repoguide",
                "-d",
                name,
            ],
            stdin=stream,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    if restored.returncode:
        (BACKUP.parent / "product-restore-error.txt").write_bytes(restored.stderr)
        raise RuntimeError(
            "Private backup restore validation failed; inspect the private log"
        )
    with readonly(local.replace("/postgres?", f"/{name}?")) as db:
        after = snapshot(db)
    if before != after:
        raise ValueError("Restored source rows do not match production")
    proof = {
        "verified": True,
        "created_at": int(time.time()),
        "schema_revision": schema,
        "backup_path": str(BACKUP.relative_to(ROOT)),
        "backup_sha256": hashlib.sha256(BACKUP.read_bytes()).hexdigest(),
        "snapshot": before,
        "restored_database": name,
        "scope": "original repository fields, chunks, vectors, symbols, edges, dependencies and source snapshots; new ownership/diagnostic columns are excluded",
    }
    PROOF.write_text(json.dumps(proof, indent=2))
    with psycopg.connect(local, autocommit=True) as db:
        db.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
    print(
        json.dumps(
            {
                "backup_verified": True,
                "repositories": len(before["repository_ids"]),
                "backup_bytes": BACKUP.stat().st_size,
            }
        )
    )


def apply(session, out, url):
    proof = json.loads(PROOF.read_text())
    if (
        not proof.get("verified")
        or hashlib.sha256(BACKUP.read_bytes()).hexdigest() != proof["backup_sha256"]
    ):
        raise ValueError("Verified private backup is required")
    ids = proof["snapshot"]["repository_ids"]
    with readonly(url) as db:
        if snapshot(db, ids) != proof["snapshot"]:
            raise ValueError(
                "Production content changed since backup; stop and take a fresh backup"
            )
    cognito = session.client("cognito-idp")
    admin = cognito.admin_get_user(
        UserPoolId=out["user_pool_id"], Username="nikhilreddy.maligireddy2@gmail.com"
    )
    subject = next(x["Value"] for x in admin["UserAttributes"] if x["Name"] == "sub")
    groups = cognito.admin_list_groups_for_user(
        UserPoolId=out["user_pool_id"], Username=admin["Username"]
    )["Groups"]
    if "repoguide-admins" not in {x["GroupName"] for x in groups}:
        raise ValueError("Expected existing administrator group membership")
    env = {
        **os.environ,
        "DATABASE_URL": url.replace("postgresql://", "postgresql+psycopg://", 1),
        "MLFLOW_ENABLED": "false",
    }
    subprocess.run(
        [sys.executable, str(ROOT / ".venv/bin/alembic"), "upgrade", "head"],
        env=env,
        cwd=ROOT,
        check=True,
    )
    with psycopg.connect(url, connect_timeout=10, row_factory=dict_row) as db:
        owners = db.execute(
            "SELECT id,owner_sub FROM repositories WHERE id=ANY(%s)", (ids,)
        ).fetchall()
        if any(x["owner_sub"] not in {"", subject} for x in owners):
            raise ValueError(
                "An existing index belongs to another user; no ownership transfer is permitted"
            )
        db.execute(
            "UPDATE repositories SET owner_sub=%s WHERE id=ANY(%s) AND owner_sub=''",
            (subject, ids),
        )
        rows = db.execute(
            "SELECT id,url,commit_sha,status,created_at FROM repositories WHERE id=ANY(%s) ORDER BY created_at DESC,id",
            (ids,),
        ).fetchall()
    os.environ["REPOGUIDE_JOB_TABLE"] = out["job_table"]
    boto3.setup_default_session(
        profile_name=session.profile_name, region_name=session.region_name
    )
    from repoguide import cloud_product as product
    from repoguide import cloud_state as state
    from repoguide.github_api import request

    state.clients.cache_clear()
    verified = {}
    latest = {}
    published = 0
    for row in rows:
        if row["url"] not in verified:
            path = urlsplit(row["url"]).path.strip("/")
            try:
                metadata, _ = request("/repos/" + path)
                verified[row["url"]] = {
                    "public": metadata.get("private") is False,
                    "branch": metadata.get("default_branch", ""),
                }
            except Exception:
                verified[row["url"]] = {"public": False, "branch": ""}
        details = verified[row["url"]]
        shared = details["public"] and row["status"] == "indexed"
        product.grant_repository(
            row["id"],
            subject,
            shared=shared,
            branch=details["branch"],
            branch_explicit=False,
            freshness_status="unknown",
            checked_at=0,
        )
        if row["url"] in latest:
            state.update(
                "repository#" + row["id"],
                "SET superseded_by=:new REMOVE catalog_pk, catalog_sk",
                {":new": latest[row["url"]]},
            )
        else:
            latest[row["url"]] = row["id"]
            published += int(shared)
    with readonly(url) as db:
        preserved = snapshot(db, ids) == proof["snapshot"]
    if not preserved:
        raise ValueError("Original repository content changed during migration")
    report = {
        "applied": True,
        "schema_revision": "b42d92e7a610",
        "legacy_indexes_owned": len(rows),
        "shared_catalog_entries": published,
        "original_source_rows_preserved": preserved,
        "backup_sha256": proof["backup_sha256"],
    }
    (ROOT / ".artifacts/product-database-rollout.json").write_text(
        json.dumps(report, indent=2)
    )
    print(json.dumps(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["audit", "backup", "apply"])
    parser.add_argument("--profile", default="repoguide")
    parser.add_argument("--region", default="us-east-2")
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    out = outputs()
    url = database_url()
    if args.phase == "audit":
        audit(session, out, url)
    elif args.phase == "backup":
        backup(url)
    else:
        apply(session, out, url)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"complete": False, "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
