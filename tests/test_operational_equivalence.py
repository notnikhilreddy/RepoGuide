"""Operational repairs may reuse AI measurements only for unchanged AI bytes."""

import hashlib
import json

import pytest

from scripts.operational_equivalence import verify


def fixture(tmp_path):
    frozen = tmp_path / ".artifacts/measured-6045"
    for base in [frozen, tmp_path]:
        source = base / "src/repoguide"
        source.mkdir(parents=True)
        (source / "answers.py").write_bytes(b"unchanged explanatory prompt")
        (source / "cloud_product.py").write_bytes(
            b"old serializer" if base == frozen else b"reviewed serializer"
        )
        for name in [
            "deployment/models.json",
            "deployment/requirements-api.txt",
            "deployment/requirements-answer.txt",
            "deployment/requirements-index.txt",
            "docker/Dockerfile.answer",
            "docker/Dockerfile.index",
            "scripts/preload_models.py",
            "scripts/stage_worker.py",
        ]:
            path = base / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"pinned runtime")

    def source_hash(base):
        return hashlib.sha256(
            b"".join(
                p.read_bytes() for p in sorted((base / "src/repoguide").glob("*.py"))
            )
        ).hexdigest()

    for base in [frozen, tmp_path]:
        (base / "deployment/release-config.json").write_text(
            json.dumps(
                {
                    "source_sha256": source_hash(base),
                    "runtime": {"model": "measured-model"},
                }
            )
        )
    (frozen / "release-config.json").write_bytes(
        (frozen / "deployment/release-config.json").read_bytes()
    )
    candidate = {
        "source_sha256": source_hash(frozen),
        "release_config_sha256": hashlib.sha256(
            (frozen / "deployment/release-config.json").read_bytes()
        ).hexdigest(),
        "image_id": "measured-image",
    }
    images = {"answer": "repaired-answer", "index": "repaired-index"}
    policy = {
        "deployment_equivalence": {
            "version": "serialization-recovery-v1",
            "deployment_source_sha256": source_hash(tmp_path),
            "deployment_image_ids": images,
            "changed_module": {
                "path": "cloud_product.py",
                "before_sha256": hashlib.sha256(b"old serializer").hexdigest(),
                "after_sha256": hashlib.sha256(b"reviewed serializer").hexdigest(),
            },
        }
    }
    return frozen, candidate, images, policy


def test_reviewed_serializer_repair_keeps_the_original_measurement_identity(tmp_path):
    _, candidate, images, policy = fixture(tmp_path)
    result = verify(tmp_path, candidate, policy, images)
    assert result["verified"]
    assert result["measured_image_id"] == "measured-image"
    assert result["deployment_image_ids"] == images
    assert result["measured_source_sha256"] != result["deployment_source_sha256"]


@pytest.mark.parametrize(
    "change", ["prompt", "model", "dependency", "image", "snapshot"]
)
def test_unreviewed_changes_cannot_reuse_measurements(tmp_path, change):
    frozen, candidate, images, policy = fixture(tmp_path)
    if change == "prompt":
        (tmp_path / "src/repoguide/answers.py").write_bytes(b"shortened prompt")
    elif change == "model":
        path = tmp_path / "deployment/release-config.json"
        value = json.loads(path.read_text())
        value["runtime"]["model"] = "different-model"
        path.write_text(json.dumps(value))
    elif change == "dependency":
        (tmp_path / "deployment/requirements-answer.txt").write_bytes(
            b"new dependencies"
        )
    elif change == "image":
        images = {**images, "answer": "unreviewed-image"}
    else:
        (frozen / "src/repoguide/answers.py").write_bytes(b"altered baseline")
    with pytest.raises(ValueError):
        verify(tmp_path, candidate, policy, images)
