"""Prepare separate API/Answer/Index SSM scopes. Values are never printed.

Default is a safe local preview. --apply requires the production quality gate,
a private backup, and creates only a bounded read role in the existing DB.
"""

from __future__ import annotations

import argparse
import json
import secrets
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from update_runtime_settings import load_settings

ROOT = Path(__file__).resolve().parents[1]


def db_url(url, username=None, password=None, *, sqlalchemy=False):
    from urllib.parse import quote

    parsed = urlsplit(url.replace("postgresql+psycopg://", "postgresql://"))
    netloc = parsed.netloc
    if username is not None:
        netloc = (
            quote(username, safe="")
            + ":"
            + quote(password, safe="")
            + "@"
            + parsed.hostname
            + ((":" + str(parsed.port)) if parsed.port else "")
        )
    query = dict(parse_qsl(parsed.query))
    query.update(sslmode="require", connect_timeout="5")
    return urlunsplit(
        (
            "postgresql+psycopg" if sqlalchemy else "postgresql",
            netloc,
            parsed.path,
            urlencode(query),
            "",
        )
    )


def create_index_writer(owner_url, source_id):
    """Create a table-scoped writer; runtime never receives the Neon owner login."""
    import psycopg
    from psycopg import sql

    name = "repoguide_index_" + source_id[:12]
    password = secrets.token_urlsafe(32)
    with psycopg.connect(owner_url, connect_timeout=5) as db:
        if db.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (name,)).fetchone():
            raise ValueError(
                "Index writer already exists; inspect its stored release credentials"
            )
        db.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
            ).format(sql.Identifier(name), sql.Literal(password))
        )
        db.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(name))
        )
        for table in [
            "repositories",
            "chunks",
            "code_symbols",
            "code_edges",
            "repo_dependencies",
            "source_files",
        ]:
            db.execute(
                sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE {} TO {}").format(
                    sql.Identifier(table), sql.Identifier(name)
                )
            )
        db.execute(
            sql.SQL("ALTER ROLE {} SET statement_timeout='120s'").format(
                sql.Identifier(name)
            )
        )
    writer_url = db_url(owner_url, name, password)
    with psycopg.connect(writer_url, connect_timeout=5) as db:
        elevated = db.execute(
            "SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles WHERE rolname=current_user"
        ).fetchone()[0]
        assert not elevated
        assert not db.execute(
            "SELECT has_schema_privilege(current_user,'public','CREATE')"
        ).fetchone()[0]
        db.execute("DELETE FROM repositories WHERE false")
        db.rollback()
    return db_url(writer_url, sqlalchemy=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--profile", default="repoguide")
    parser.add_argument("--region", default="us-east-2")
    parser.add_argument("--prefix", default="/repoguide/demo")
    parser.add_argument("--backup", default=".artifacts/private/neon-before.dump")
    args = parser.parse_args()
    values = load_settings(ROOT / ".env.deploy")
    manifest = json.loads((ROOT / "deployment/release-config.json").read_text())
    provider_keys = {
        "openai": ["OPENAI_API_KEY"],
        "gemini": ["GEMINI_API_KEY"],
        "opencode": ["OPENCODE_API_KEY"],
        "ollama": [],
    }[manifest["runtime"]["LLM_PROVIDER"]]
    scopes = {
        "api": ["READ_DATABASE_URL"],
        "answer": [
            "DATABASE_URL",
            *provider_keys,
            *(
                ["JEV_API_KEY"]
                if manifest["runtime"]["ROUTER_PROVIDER"] == "jev"
                else []
            ),
            "CONTEXT7_API_KEY",
            "UPSTASH_REDIS_REST_URL",
            "UPSTASH_REDIS_REST_TOKEN",
        ],
        "index": ["DATABASE_URL"],
    }
    print(
        json.dumps(
            {
                "parameters": {
                    args.prefix + "/" + k: fields for k, fields in scopes.items()
                },
                "apply": args.apply,
            },
            indent=2,
        )
    )
    if not args.apply:
        return
    from release_cloud import verify

    verify()
    backup = ROOT / args.backup
    if not backup.exists() or backup.stat().st_size == 0:
        raise ValueError("A private tested backup is required first")
    import boto3
    import psycopg
    from psycopg import sql

    reader = "repoguide_api_" + manifest["source_sha256"][:12]
    password = secrets.token_urlsafe(32)
    owner_url = db_url(values["DATABASE_URL"])
    with psycopg.connect(owner_url, connect_timeout=5) as db:
        if db.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (reader,)).fetchone():
            raise ValueError(
                "Release read role already exists; inspect the existing SSM release before rotating it"
            )
        db.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
            ).format(sql.Identifier(reader), sql.Literal(password))
        )
        db.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(reader))
        )
        for table in [
            "repositories",
            "chunks",
            "code_symbols",
            "code_edges",
            "repo_dependencies",
            "source_files",
        ]:
            db.execute(
                sql.SQL("GRANT SELECT ON TABLE {} TO {}").format(
                    sql.Identifier(table), sql.Identifier(reader)
                )
            )
        db.execute(
            sql.SQL("ALTER ROLE {} SET default_transaction_read_only=on").format(
                sql.Identifier(reader)
            )
        )
        db.execute(
            sql.SQL("ALTER ROLE {} SET statement_timeout='2500ms'").format(
                sql.Identifier(reader)
            )
        )
    read_url = db_url(owner_url, reader, password)
    with psycopg.connect(read_url, connect_timeout=5) as db:
        db.execute("SELECT count(*) FROM repositories").fetchone()
        try:
            db.execute("DELETE FROM repositories WHERE false")
        except (
            psycopg.errors.ReadOnlySqlTransaction,
            psycopg.errors.InsufficientPrivilege,
        ):
            db.rollback()
        else:
            raise ValueError("Read role write denial failed")
    api = {"READ_DATABASE_URL": read_url}
    answer = {
        "DATABASE_URL": db_url(read_url, sqlalchemy=True),
        **{
            k: values[k]
            for k in scopes["answer"]
            if k != "DATABASE_URL" and values.get(k)
        },
    }
    # GitHub MCP remains intentionally disabled for this release.
    index = {"DATABASE_URL": create_index_writer(owner_url, manifest["source_sha256"])}
    ssm = boto3.Session(profile_name=args.profile, region_name=args.region).client(
        "ssm"
    )
    for kind, config in [("api", api), ("answer", answer), ("index", index)]:
        ssm.put_parameter(
            Name=args.prefix + "/" + kind,
            Value=json.dumps(config, separators=(",", ":")),
            Type="SecureString",
            Overwrite=True,
        )
    print(
        "Three scoped SecureStrings written; no values exported to Terraform or terminal"
    )


if __name__ == "__main__":
    main()
