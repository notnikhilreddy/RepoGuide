"""Compare original repository rows with a locally restored predeployment backup.

Both connections are read-only. New smoke repositories are excluded by deriving
repository IDs from the backup, never from the current production contents.
"""

import hashlib
import json
from pathlib import Path

import psycopg
from psycopg import sql
from update_runtime_settings import load_settings

root = Path(__file__).resolve().parents[1]
settings = load_settings(root / ".env.deploy")
owner = settings["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
local = "postgresql://repoguide:repoguide@127.0.0.1:55432/repoguide_backup_verify_20261105?sslmode=require"
tables = [
    "repositories",
    "chunks",
    "code_symbols",
    "code_edges",
    "repo_dependencies",
    "source_files",
]


def snapshot(connection, ids):
    result = {}
    for repo_id in ids:
        result[repo_id] = {}
        for table in tables:
            key = "id" if table == "repositories" else "repo_id"
            query = sql.SQL(
                'SELECT to_jsonb(t)::text FROM {} t WHERE {}=%s ORDER BY to_jsonb(t)::text COLLATE "C"'
            ).format(sql.Identifier(table), sql.Identifier(key))
            digest = hashlib.sha256()
            rows = 0
            for (content,) in connection.execute(query, (repo_id,)):
                digest.update(content.encode() + b"\n")
                rows += 1
            result[repo_id][table] = {"rows": rows, "sha256": digest.hexdigest()}
    return result


with psycopg.connect(local, options="-c default_transaction_read_only=on") as restored:
    ids = [
        str(row[0])
        for row in restored.execute("SELECT id FROM repositories ORDER BY id")
    ]
    assert ids, "Restored backup must contain the original repository"
    before = snapshot(restored, ids)
with psycopg.connect(
    owner, options="-c default_transaction_read_only=on", connect_timeout=10
) as production:
    after = snapshot(production, ids)
    revision = production.execute("SELECT version_num FROM alembic_version").fetchone()[
        0
    ]
report = {
    "live_neon": True,
    "restored_backup": ".artifacts/private/neon-before-openai.dump",
    "comparison": "all original repository row values, including embeddings and exact source snapshots",
    "passed": before == after,
    "schema_revision": revision,
    "before": before,
    "after": after,
}
(root / ".artifacts/neon-deployment-preservation.json").write_text(
    json.dumps(report, indent=2)
)
assert report["passed"], "Original repository data changed"
print(
    json.dumps(
        {"passed": True, "original_repositories": len(ids), "schema_revision": revision}
    )
)
