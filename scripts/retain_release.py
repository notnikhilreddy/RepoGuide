"""Retain immutable technical artifacts without creating an approved baseline."""

import argparse
import base64
import hashlib
import json
import subprocess

import boto3
from botocore.exceptions import ClientError
from release_cloud import ROOT, verify

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--final", action="store_true")
args = parser.parse_args()
verify()
manifest = json.loads((ROOT / ".artifacts/release-manifest.json").read_text())
if args.final:
    subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(ROOT / "scripts/collect_deployment_validation.py"),
            "--require-complete",
        ],
        check=True,
    )
outputs = json.loads(
    subprocess.check_output(
        ["terraform", "-chdir=" + str(ROOT / "infra/terraform"), "output", "-json"]
    )
)
bucket = outputs["artifact_bucket"]["value"]
s3 = boto3.Session(profile_name="repoguide", region_name="us-east-2").client("s3")
paths = [
    "deployment/api.zip",
    "deployment/controller.zip",
    "deployment/models.json",
    "deployment/release-config.json",
    "deployment/requirements-api.txt",
    "deployment/requirements-answer.txt",
    "deployment/requirements-index.txt",
    ".artifacts/release-source.tar",
    ".artifacts/release-manifest.json",
    ".artifacts/package-inventory.json",
    ".artifacts/security-summary.json",
    ".artifacts/answer-inventory.json",
    ".artifacts/index-inventory.json",
    ".artifacts/answer-sbom.cdx.json",
    ".artifacts/index-sbom.cdx.json",
    ".artifacts/answer-vulnerabilities.json",
    ".artifacts/index-vulnerabilities.json",
    ".artifacts/packaged-api-smoke.json",
    ".artifacts/local-workers.json",
]
if manifest["quality"]["status"] == "passed":
    paths += [
        ".artifacts/baseline-evaluation.json",
        ".artifacts/candidate-evaluation.json",
        ".artifacts/quality-comparison.json",
        "deployment/evaluator-config.json",
        "evals/release_cases.json",
        "evals/release_routes.json",
    ]
    if manifest["quality"].get("acceptance") == "owner_accepted_measured_tradeoffs":
        paths += [
            ".artifacts/strict-quality-comparison.json",
            "deployment/product-quality-acceptance.json",
        ]
if args.final:
    paths += [
        ".artifacts/product-database-rollout.json",
        ".artifacts/product-live-api-smoke.json",
        ".artifacts/product-incremental-live-smoke.json",
        ".artifacts/product-incremental-browser.json",
        ".artifacts/published-evaluation-catalog.json",
        ".artifacts/product-cloud-cleanup.json",
        ".artifacts/product-vercel-cleanup.json",
        ".artifacts/product-resource-inventory.json",
        ".artifacts/product-source-secret-scan.json",
        ".artifacts/product-local-validation.json",
        ".artifacts/product-eval/spend.json",
        ".artifacts/playwright-results.json",
        "docs/deployment/product-release.md",
    ]
    paths += [
        "reports/deployment-validation.json",
        ".artifacts/aws-idle-verification.json",
        ".artifacts/aws-final-smoke.json",
        ".artifacts/aws-security-review.json",
        ".artifacts/aws-rate-verification.json",
        ".artifacts/neon-deployment-preservation.json",
        ".artifacts/aws-component-rollback.json",
        ".artifacts/vercel-cutover.json",
        ".artifacts/browser-production-smoke.json",
        ".artifacts/deployment-cleanup.json",
        ".artifacts/source-secret-scan.json",
        ".artifacts/smoke-dlq-cleanup.json",
        ".artifacts/vercel-source-equivalence.json",
        "docs/deployment/README.md",
        "docs/deployment/release-evidence.md",
        "docs/deployment/runbooks.md",
        "docs/deployment/sizing.md",
        "docs/deployment/cost-estimate.md",
    ]
report = []
for relative in paths:
    path = ROOT / relative
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    key = (
        "releases/"
        + manifest["release_id"]
        + "/"
        + relative.removeprefix(".artifacts/")
    )
    try:
        result = s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=content,
            ServerSideEncryption="AES256",
            ChecksumSHA256=base64.b64encode(bytes.fromhex(digest)).decode(),
            Metadata={
                "sha256": digest,
                "quality-status": manifest["quality"]["status"],
            },
            IfNoneMatch="*",
        )
        version = result["VersionId"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "PreconditionFailed":
            raise
        existing = s3.get_object(Bucket=bucket, Key=key)
        assert hashlib.sha256(existing["Body"].read()).hexdigest() == digest, (
            "Existing immutable artifact differs: " + relative
        )
        version = existing["VersionId"]
    report.append({"path": relative, "key": key, "sha256": digest, "version": version})
receipt = (
    ROOT
    / ".artifacts"
    / ("release-retention-final.json" if args.final else "release-retention-core.json")
)
receipt.write_text(
    json.dumps(
        {
            "private_versioned_s3": True,
            "quality_baseline_created": False,
            "objects": report,
        },
        indent=2,
    )
)
print(
    json.dumps(
        {
            "objects_retained": len(report),
            "quality_status": manifest["quality"]["status"],
            "approved_baseline_created": False,
        }
    )
)
