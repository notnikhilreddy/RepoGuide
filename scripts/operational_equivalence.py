"""Bind a serialization-only deployment repair to unchanged measured AI code.

Never rewrites evaluation results or claims the repaired image was remeasured.
The only allowed source difference is the exact reviewed cloud_product.py hash.
"""

from __future__ import annotations

import hashlib
import json


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def verify(root, candidate, policy, images):
    proof = policy.get("deployment_equivalence", {})
    if proof.get("version") != "serialization-recovery-v1":
        raise ValueError("A reviewed operational-equivalence record is required")
    frozen = root / ".artifacts/measured-6045"
    before = frozen / "src/repoguide"
    after = root / "src/repoguide"
    old = {p.name: p.read_bytes() for p in sorted(before.glob("*.py"))}
    new = {p.name: p.read_bytes() for p in sorted(after.glob("*.py"))}
    if (
        set(old) != set(new)
        or digest(b"".join(old.values())) != candidate["source_sha256"]
    ):
        raise ValueError("Measured source snapshot mismatch")
    changed = [name for name in old if old[name] != new[name]]
    if changed != ["cloud_product.py"]:
        raise ValueError(
            "Answer/retrieval source changed; measurements cannot be reused"
        )
    source = digest(b"".join(new.values()))
    if (
        source != proof.get("deployment_source_sha256")
        or proof.get("changed_module")
        != {
            "path": "cloud_product.py",
            "before_sha256": digest(old["cloud_product.py"]),
            "after_sha256": digest(new["cloud_product.py"]),
        }
        or images != proof.get("deployment_image_ids")
    ):
        raise ValueError("Operational repair or image differs from the reviewed record")
    raw = (frozen / "release-config.json").read_bytes()
    if digest(raw) != candidate["release_config_sha256"]:
        raise ValueError("Measured configuration snapshot mismatch")
    left = json.loads(raw)
    right = json.loads((root / "deployment/release-config.json").read_bytes())
    if right.pop("source_sha256") != source:
        raise ValueError("Deployment configuration has the wrong source identity")
    left.pop("source_sha256")
    if left != right:
        raise ValueError(
            "Model/router configuration changed; measurements cannot be reused"
        )
    files = [
        "deployment/models.json",
        "deployment/requirements-api.txt",
        "deployment/requirements-answer.txt",
        "deployment/requirements-index.txt",
        "docker/Dockerfile.answer",
        "docker/Dockerfile.index",
        "scripts/preload_models.py",
        "scripts/stage_worker.py",
    ]
    identities = {}
    for name in files:
        previous = frozen / name
        if previous.read_bytes() != (root / name).read_bytes():
            raise ValueError("Runtime dependencies/model staging changed: " + name)
        identities[name] = digest(previous.read_bytes())
    return {
        "verified": True,
        "measured_source_sha256": candidate["source_sha256"],
        "measured_image_id": candidate["image_id"],
        "deployment_source_sha256": source,
        "deployment_image_ids": images,
        "changed_module": proof["changed_module"],
        "unchanged_dependency_identities": identities,
        "scope": "Existing live scores describe the unchanged answer/retrieval modules. Only DynamoDB-number serialization for S3 chat delivery changed; this deployment image has separate functional validation.",
    }
