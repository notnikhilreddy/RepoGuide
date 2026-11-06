"""Publish exact tested images with explicit, truthful release authorization.

Live evaluation remains the default. An owner-authorized exception must bind to
the exact source, config and local images; it never fabricates passing scores.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evals.product_release_policy import measured_comparison  # noqa: E402
from evals.release_gate import compare  # noqa: E402


def source_hash():
    return hashlib.sha256(
        b"".join(p.read_bytes() for p in sorted((ROOT / "src/repoguide").glob("*.py")))
    ).hexdigest()


def release_fingerprint():
    digest = hashlib.sha256()
    paths = [
        ROOT / "deployment/release-config.json",
        ROOT / "deployment/models.json",
        ROOT / "deployment/evaluator-config.json",
        ROOT / "deployment/product-quality-acceptance.json",
        ROOT / "deployment/requirements-api.txt",
        ROOT / "deployment/requirements-answer.txt",
        ROOT / "deployment/requirements-index.txt",
        ROOT / "docker/Dockerfile.answer",
        ROOT / "docker/Dockerfile.index",
        ROOT / "frontend/package-lock.json",
        ROOT / "frontend/vercel.json",
        ROOT / "frontend/vite.config.ts",
        ROOT / "scripts/stage_worker.py",
        ROOT / "scripts/release_cloud.py",
        ROOT / "scripts/configure_cloud_secrets.py",
    ]
    paths += sorted((ROOT / "frontend/src").rglob("*"))
    paths += sorted((ROOT / "infra/terraform").glob("*.tf"))
    for path in paths:
        if path.is_file():
            digest.update(
                str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes()
            )
    return digest.hexdigest()


def approved_source_hash():
    paths = subprocess.check_output(
        [
            "git",
            "ls-tree",
            "-r",
            "--name-only",
            "4aa70f5cbf345ab83ab7cc14257d79da6a8ee416",
            "src/repoguide",
        ],
        cwd=ROOT,
        text=True,
    ).splitlines()
    files = sorted(
        path for path in paths if path.endswith(".py") and path.count("/") == 2
    )
    return hashlib.sha256(
        b"".join(
            subprocess.check_output(
                ["git", "show", "4aa70f5cbf345ab83ab7cc14257d79da6a8ee416:" + path],
                cwd=ROOT,
            )
            for path in files
        )
    ).hexdigest()


def initial_bootstrap_allowed(candidate):
    state_path = ROOT / "infra/terraform/terraform.tfstate"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    has_api = any(
        r.get("type") == "aws_lambda_function" and r.get("name") == "api"
        for r in state.get("resources", [])
    )
    if not has_api:
        return True
    path = ROOT / ".artifacts/release-manifest.json"
    existing = json.loads(path.read_text()) if path.exists() else {}
    return (
        existing.get("bootstrap") is True
        and existing.get("source_sha256") == candidate["source_sha256"]
        and existing.get("release_id") == "release-" + release_fingerprint()[:16]
    )


def deployed_baseline_verified(baseline):
    """First measurement only; never supersedes an approved quality report."""
    folder = ROOT / ".artifacts/improvement-baseline"
    try:
        proof = json.loads((folder / "production-provenance.json").read_text())
        manifest_raw = (folder / "deployed-manifest.json").read_bytes()
        manifest = json.loads(manifest_raw)
        snapshot = folder / "src/repoguide"
        snapshot_hash = hashlib.sha256(
            b"".join(p.read_bytes() for p in sorted(snapshot.glob("*.py")))
        ).hexdigest()
        return (
            proof.get("verified") is True
            and manifest["quality"]["status"] == "skipped_by_owner"
            and proof["archived_manifest_sha256"]
            == hashlib.sha256(manifest_raw).hexdigest()
            and manifest["release_id"] == proof["release_id"]
            and manifest["source_sha256"]
            == proof["source_sha256"]
            == baseline["source_sha256"]
            == snapshot_hash
            and proof["image_id"]
            == baseline["image_id"]
            == manifest["images"]["answer"].split("@")[-1]
            and proof["release_config_sha256"]
            == baseline["release_config_sha256"]
            == hashlib.sha256((folder / "release-config.json").read_bytes()).hexdigest()
        )
    except (OSError, KeyError, ValueError):
        return False


def verify_evaluation():
    artifacts = ROOT / ".artifacts"
    baseline = json.loads((artifacts / "baseline-evaluation.json").read_text())
    candidate = json.loads((artifacts / "candidate-evaluation.json").read_text())
    policy_path = ROOT / "deployment/product-quality-acceptance.json"
    policy = json.loads(policy_path.read_text()) if policy_path.exists() else None
    result = measured_comparison(baseline, candidate, policy)
    (artifacts / "quality-comparison.json").write_text(json.dumps(result, indent=2))
    if not result["passed"]:
        raise ValueError("Non-regression gate rejected the candidate")
    equivalence = None
    if candidate["source_sha256"] != source_hash():
        from scripts.operational_equivalence import verify as verify_equivalence

        images = {
            kind: subprocess.check_output(
                [
                    "docker",
                    "image",
                    "inspect",
                    "repoguide-" + kind + ":candidate",
                    "--format",
                    "{{.Id}}",
                ],
                text=True,
            ).strip()
            for kind in ["answer", "index"]
        }
        equivalence = verify_equivalence(ROOT, candidate, policy or {}, images)
        result["deployment_equivalence"] = equivalence
        (artifacts / "evaluation-equivalence.json").write_text(
            json.dumps(equivalence, indent=2)
        )
    approved = artifacts / "approved-evaluation.json"
    if approved.exists():
        historical = compare(json.loads(approved.read_text()), candidate)
        if not historical["passed"]:
            raise ValueError(
                "Candidate regresses or is inconclusive against the last approved production report"
            )
    elif not deployed_baseline_verified(baseline) and (
        not initial_bootstrap_allowed(candidate)
        or baseline["source_sha256"] != approved_source_hash()
    ):
        raise ValueError(
            "Protected last-approved baseline is required; it cannot be reset to a poorer fresh run"
        )
    model = json.loads((ROOT / "deployment/release-config.json").read_text())
    if (
        model["source_sha256"] != source_hash()
        or not equivalence
        and candidate["release_config_sha256"]
        != hashlib.sha256(
            (ROOT / "deployment/release-config.json").read_bytes()
        ).hexdigest()
    ):
        raise ValueError("Release configuration changed after evaluation")
    evaluator_config = json.loads(
        (ROOT / "deployment/evaluator-config.json").read_text()
    )
    expected_scorer = (
        evaluator_config["version"]
        + ":"
        + hashlib.sha256(
            (ROOT / "evals/release_eval.py").read_bytes()
            + json.dumps(evaluator_config, sort_keys=True).encode()
        ).hexdigest()
    )
    if candidate["metadata"]["scorer_version"] != expected_scorer:
        raise ValueError("Evaluator changed after the measured comparison")
    image = subprocess.check_output(
        [
            "docker",
            "image",
            "inspect",
            "repoguide-answer:candidate",
            "--format",
            "{{.Id}}",
        ],
        text=True,
    ).strip()
    if candidate["image_id"] != image and not equivalence:
        raise ValueError("Candidate image differs from evaluated image")
    (artifacts / "quality-comparison.json").write_text(json.dumps(result, indent=2))
    return {**result, "status": "passed"}


def verify():
    artifacts = ROOT / ".artifacts"
    authorization = ROOT / "deployment/release-authorization.json"
    if authorization.exists():
        policy = json.loads(authorization.read_text())
        if (
            policy.get("quality_evaluation") != "skipped_by_owner"
            or policy.get("source_sha256") != source_hash()
            or policy.get("release_fingerprint") != release_fingerprint()
            or policy.get("scope") != "initial-openai-deployment"
        ):
            raise ValueError("Owner authorization does not match this exact release")
        for kind in ["answer", "index"]:
            image = subprocess.check_output(
                [
                    "docker",
                    "image",
                    "inspect",
                    "repoguide-" + kind + ":candidate",
                    "--format",
                    "{{.Id}}",
                ],
                text=True,
            ).strip()
            if policy.get("local_image_ids", {}).get(kind) != image:
                raise ValueError("Owner authorization image changed")
        result = {
            "status": "skipped_by_owner",
            "evaluation_passed": False,
            "scope": policy["scope"],
        }
    else:
        result = verify_evaluation()
    model = json.loads((ROOT / "deployment/release-config.json").read_text())
    if model["source_sha256"] != source_hash():
        raise ValueError("Source changed after configuration freeze")
    smoke = json.loads((artifacts / "packaged-api-smoke.json").read_text())
    if (
        not smoke.get("readonly_enforced")
        or smoke["warm_list_p95_seconds"] > 1
        or smoke.get("zip_sha256")
        != hashlib.sha256((ROOT / "deployment/api.zip").read_bytes()).hexdigest()
    ):
        raise ValueError("Packaged read API failed its browsing gate")
    workers = json.loads((artifacts / "local-workers.json").read_text())
    if not all(
        workers.get(k, {}).get("fail_then_success") for k in ["answer", "index"]
    ):
        raise ValueError("Real container failure-isolation gate missing")
    for kind in ["answer", "index"]:
        current = subprocess.check_output(
            [
                "docker",
                "image",
                "inspect",
                "repoguide-" + kind + ":candidate",
                "--format",
                "{{.Id}}",
            ],
            text=True,
        ).strip()
        if workers[kind]["image_id"] != current:
            raise ValueError("Worker image changed after container tests")
    security = json.loads((artifacts / "security-summary.json").read_text())
    for kind in ["answer", "index"]:
        scan = security["images"][kind]
        current = subprocess.check_output(
            [
                "docker",
                "image",
                "inspect",
                "repoguide-" + kind + ":candidate",
                "--format",
                "{{.Id}}",
            ],
            text=True,
        ).strip()
        if (
            scan["image_id"] != current
            or not scan["cpu_only"]
            or scan["secret_findings"]
            or scan["critical"]
            or scan["fixable_high"]
        ):
            raise ValueError("Current image security scan is missing or blocked")
    (artifacts / "release-approval.json").write_text(
        json.dumps(
            {
                "technical_checks_passed": True,
                "quality_status": result["status"],
                "source_sha256": source_hash(),
                "release_fingerprint": release_fingerprint(),
            },
            indent=2,
        )
    )
    return result


def publish(profile, region):
    import boto3

    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    )
    if (
        any(line[3:] != "plan.md" for line in dirty.splitlines())
        and not (ROOT / "deployment/release-authorization.json").exists()
    ):
        raise ValueError(
            "Commit the reviewed release before publishing; the Git SHA must identify the deployed bytes"
        )
    result = verify()
    source_archive = ROOT / ".artifacts/release-source.tar"
    files = []
    for directory in [
        "src",
        "scripts",
        "docker",
        "evals",
        "deployment",
        "migrations",
        "frontend/src",
        "infra/terraform",
    ]:
        files += [
            p
            for p in (ROOT / directory).rglob("*")
            if p.is_file()
            and not p.name.endswith(".tfvars.json")
            and p.suffix
            in {".py", ".tf", ".json", ".txt", ".in", ".tsx", ".ts", ".css"}
            and not any(x in p.parts for x in ["__pycache__", ".terraform"])
        ]
    files += list((ROOT / "docker").glob("Dockerfile.*"))
    files += [
        ROOT / "frontend" / n
        for n in [
            "package.json",
            "package-lock.json",
            "index.html",
            "vite.config.ts",
            "vercel.json",
        ]
    ]
    with tarfile.open(source_archive, "w") as archive:
        for path in sorted(set(files)):
            info = archive.gettarinfo(str(path), str(path.relative_to(ROOT)))
            info.uid = info.gid = info.mtime = 0
            info.uname = info.gname = ""
            with path.open("rb") as stream:
                archive.addfile(info, stream)
    from update_runtime_settings import load_settings

    known_credentials = set()
    for path in [ROOT / ".env", ROOT / ".env.deploy", ROOT / ".env.local"]:
        if path.exists():
            known_credentials.update(
                value.encode()
                for key, value in load_settings(path).items()
                if len(value) > 12
                and any(
                    word in key
                    for word in [
                        "API_KEY",
                        "TOKEN",
                        "SECRET",
                        "PASSWORD",
                        "DATABASE_URL",
                    ]
                )
            )
    for path in [
        source_archive,
        ROOT / "deployment/api.zip",
        ROOT / "deployment/controller.zip",
    ]:
        if any(secret in path.read_bytes() for secret in known_credentials):
            raise ValueError("Runtime credential found in a release artifact")
    session = boto3.Session(profile_name=profile, region_name=region)
    ecr = session.client("ecr")
    import base64

    auth = ecr.get_authorization_token()["authorizationData"][0]
    username, password = (
        base64.b64decode(auth["authorizationToken"]).decode().split(":", 1)
    )
    subprocess.run(
        [
            "docker",
            "login",
            "--username",
            username,
            "--password-stdin",
            auth["proxyEndpoint"],
        ],
        input=password,
        text=True,
        stdout=subprocess.DEVNULL,
        check=True,
    )
    account = session.client("sts").get_caller_identity()["Account"]
    tag = "release-" + release_fingerprint()[:16]
    images = {}
    for kind in ["answer", "index"]:
        local = "repoguide-" + kind + ":candidate"
        repository = "repoguide-demo/" + kind
        uri = f"{account}.dkr.ecr.{region}.amazonaws.com/{repository}"
        subprocess.run(["docker", "tag", local, uri + ":" + tag], check=True)
        subprocess.run(["docker", "push", uri + ":" + tag], check=True)
        digest = ecr.describe_images(
            repositoryName=repository, imageIds=[{"imageTag": tag}]
        )["imageDetails"][0]["imageDigest"]
        images[kind] = uri + "@" + digest
    manifest = {
        "bootstrap": not (ROOT / ".artifacts/approved-evaluation.json").exists(),
        "git_sha": None
        if dirty.strip()
        else subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "base_git_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "source_status": "working_tree" if dirty.strip() else "committed",
        "release_fingerprint": release_fingerprint(),
        "source_archive_sha256": hashlib.sha256(
            source_archive.read_bytes()
        ).hexdigest(),
        "packages": json.loads(
            (ROOT / ".artifacts/package-inventory.json").read_text()
        ),
        "runtime": json.loads((ROOT / "deployment/release-config.json").read_text())[
            "runtime"
        ],
        "release_id": tag,
        "source_sha256": source_hash(),
        "images": images,
        "quality": result,
    }
    (ROOT / ".artifacts/release-manifest.json").write_text(
        json.dumps(manifest, indent=2)
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["verify", "publish"])
    parser.add_argument("--profile", default=os.getenv("AWS_PROFILE"))
    parser.add_argument("--region", default="us-east-2")
    args = parser.parse_args()
    print(
        json.dumps(
            verify() if args.action == "verify" else publish(args.profile, args.region),
            indent=2,
        )
    )
