"""Bind the first measured baseline to the deployed, previously unevaluated release.

Read-only AWS checks. Never replaces a protected approved report or baseline.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT / ".artifacts/improvement-baseline"
    observation = json.loads(
        (ROOT / ".artifacts/product-cloud-before.json").read_text()
    )
    session = boto3.Session(profile_name="repoguide", region_name="us-east-2")
    if session.client("sts").get_caller_identity()["Account"] != observation["account"]:
        raise ValueError("Account mismatch")
    bucket = observation["outputs"]["artifact_bucket"]
    s3 = session.client("s3")
    prefix = "releases/" + observation["release_id"] + "/"
    manifest_raw = s3.get_object(Bucket=bucket, Key=prefix + "release-manifest.json")[
        "Body"
    ].read()
    manifest = json.loads(manifest_raw)
    config_raw = s3.get_object(
        Bucket=bucket, Key=prefix + "deployment/release-config.json"
    )["Body"].read()
    config = json.loads(config_raw)
    package = s3.get_object(Bucket=bucket, Key=prefix + "deployment/api.zip")[
        "Body"
    ].read()
    identity = json.loads((folder / "identity.json").read_text())
    if manifest["quality"]["status"] != "skipped_by_owner":
        raise ValueError(
            "An evaluated release must use its protected approved baseline"
        )
    if (
        manifest["source_sha256"] != config["source_sha256"]
        or identity["source_sha256"] != config["source_sha256"]
    ):
        raise ValueError("Source identity mismatch")
    if config_raw != (folder / "release-config.json").read_bytes():
        raise ValueError("Snapshot configuration mismatch")
    current = session.client("lambda").get_function_configuration(
        FunctionName=observation["outputs"]["api_function"]
    )
    if (
        current["Environment"]["Variables"]["REPOGUIDE_RELEASE"]
        != manifest["release_id"]
        or current["CodeSha256"]
        != base64.b64encode(hashlib.sha256(package).digest()).decode()
    ):
        raise ValueError("Deployed API differs from archived release")
    ecs = session.client("ecs")
    for kind, name in observation["outputs"]["ecs_services"].items():
        service = ecs.describe_services(
            cluster=observation["outputs"]["ecs_cluster"], services=[name]
        )["services"][0]
        task = ecs.describe_task_definition(taskDefinition=service["taskDefinition"])[
            "taskDefinition"
        ]
        if (
            task["containerDefinitions"][0]["image"] != manifest["images"][kind]
            or observation["workers"][kind]["image"] != manifest["images"][kind]
        ):
            raise ValueError("Deployed worker differs from archived release")
    if manifest["images"]["answer"].split("@")[-1] != identity["image"]:
        raise ValueError("Measured baseline image is not deployed")
    report = {
        "verified": True,
        "release_id": manifest["release_id"],
        "source_sha256": config["source_sha256"],
        "image_id": identity["image"],
        "release_config_sha256": hashlib.sha256(config_raw).hexdigest(),
        "archived_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "account": observation["account"],
        "api_code_sha256": current["CodeSha256"],
        "method": "Read-only current Lambda and ECS identities compared with immutable versioned S3 release artifacts; no previously approved evaluation exists.",
    }
    path = folder / "production-provenance.json"
    if path.exists() and json.loads(path.read_text()) != report:
        raise ValueError("Protected production provenance differs")
    path.write_text(json.dumps(report, indent=2) + "\n")
    (folder / "deployed-manifest.json").write_bytes(manifest_raw)
    print(
        json.dumps(
            {
                "verified": True,
                "release_id": manifest["release_id"],
                "source_sha256": config["source_sha256"],
            }
        )
    )


if __name__ == "__main__":
    main()
