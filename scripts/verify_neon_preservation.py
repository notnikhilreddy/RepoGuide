"""Read-only verification of original index content against the restored backup proof."""

from __future__ import annotations

import hashlib
import json

from product_database_rollout import (
    BACKUP,
    PROOF,
    ROOT,
    database_url,
    readonly,
    snapshot,
)


def main():
    proof = json.loads(PROOF.read_text())
    if (
        not proof.get("verified")
        or hashlib.sha256(BACKUP.read_bytes()).hexdigest() != proof["backup_sha256"]
    ):
        raise ValueError("Verified restored backup required")
    before = proof["snapshot"]
    with readonly(database_url()) as db:
        after = snapshot(db, before["repository_ids"])
        revision = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    report = {
        "live_neon": True,
        "restored_backup": proof["backup_path"],
        "backup_sha256": proof["backup_sha256"],
        "comparison": proof["scope"],
        "passed": before == after,
        "schema_revision": revision,
        "before": before,
        "after": after,
    }
    (ROOT / ".artifacts/neon-deployment-preservation.json").write_text(
        json.dumps(report, indent=2)
    )
    if not report["passed"]:
        raise ValueError("Original repository content changed")
    print(
        json.dumps(
            {
                "passed": True,
                "original_repositories": len(before["repository_ids"]),
                "schema_revision": revision,
            }
        )
    )


if __name__ == "__main__":
    main()
