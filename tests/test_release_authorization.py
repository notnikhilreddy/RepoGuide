import json

import pytest

from scripts import release_cloud


def prepare(monkeypatch, tmp_path):
    monkeypatch.setattr(release_cloud, "ROOT", tmp_path)
    monkeypatch.setattr(release_cloud, "source_hash", lambda: "source")
    monkeypatch.setattr(release_cloud, "release_fingerprint", lambda: "configuration")
    (tmp_path / "deployment").mkdir()
    policy = {
        "scope": "initial-openai-deployment",
        "quality_evaluation": "skipped_by_owner",
        "source_sha256": "source",
        "release_fingerprint": "configuration",
        "local_image_ids": {"answer": "image", "index": "image"},
    }
    return policy


def write(tmp_path, policy):
    (tmp_path / "deployment/release-authorization.json").write_text(json.dumps(policy))


def test_quality_skip_cannot_authorize_changed_source(monkeypatch, tmp_path):
    policy = prepare(monkeypatch, tmp_path)
    policy["source_sha256"] = "different-source"
    write(tmp_path, policy)
    with pytest.raises(ValueError, match="exact release"):
        release_cloud.verify()


def test_quality_skip_cannot_authorize_changed_image(monkeypatch, tmp_path):
    policy = prepare(monkeypatch, tmp_path)
    write(tmp_path, policy)
    monkeypatch.setattr(
        release_cloud.subprocess, "check_output", lambda *a, **kw: "other-image"
    )
    with pytest.raises(ValueError, match="image changed"):
        release_cloud.verify()


def test_quality_skip_still_requires_real_technical_evidence(monkeypatch, tmp_path):
    policy = prepare(monkeypatch, tmp_path)
    write(tmp_path, policy)
    monkeypatch.setattr(
        release_cloud.subprocess, "check_output", lambda *a, **kw: "image"
    )
    (tmp_path / "deployment/release-config.json").write_text(
        json.dumps({"source_sha256": "source"})
    )
    with pytest.raises(FileNotFoundError, match="packaged-api-smoke"):
        release_cloud.verify()
    assert not (tmp_path / ".artifacts/quality-comparison.json").exists()


def test_first_measurement_requires_exact_deployed_provenance(monkeypatch, tmp_path):
    import hashlib

    monkeypatch.setattr(release_cloud, "ROOT", tmp_path)
    folder = tmp_path / ".artifacts/improvement-baseline"
    source = folder / "src/repoguide"
    source.mkdir(parents=True)
    (source / "pipeline.py").write_text("immutable deployed source")
    digest = hashlib.sha256((source / "pipeline.py").read_bytes()).hexdigest()
    config = b'{"runtime": {}}\n'
    (folder / "release-config.json").write_bytes(config)
    config_hash = hashlib.sha256(config).hexdigest()
    image = "sha256:" + "a" * 64
    manifest = {
        "release_id": "deployed",
        "quality": {"status": "skipped_by_owner"},
        "source_sha256": digest,
        "images": {"answer": "example@" + image},
    }
    raw = json.dumps(manifest).encode()
    (folder / "deployed-manifest.json").write_bytes(raw)
    proof = {
        "verified": True,
        "release_id": "deployed",
        "source_sha256": digest,
        "image_id": image,
        "release_config_sha256": config_hash,
        "archived_manifest_sha256": hashlib.sha256(raw).hexdigest(),
    }
    (folder / "production-provenance.json").write_text(json.dumps(proof))
    report = {
        "source_sha256": digest,
        "image_id": image,
        "release_config_sha256": config_hash,
    }
    assert release_cloud.deployed_baseline_verified(report)
    assert not release_cloud.deployed_baseline_verified(
        {**report, "image_id": "different"}
    )
    (source / "pipeline.py").write_text("poorer replacement baseline")
    assert not release_cloud.deployed_baseline_verified(report)
