"""Promote measured baseline only after complete, real post-deploy evidence.

No waiver/skip switch. Owner-skipped quality evaluation cannot create an
approved baseline even when real functional AWS acceptance succeeds.
"""

import argparse
import json
from pathlib import Path

from baseline_reference import select_reference
from release_cloud import ROOT, verify

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--bucket", required=True)
p.add_argument("--smoke", default=".artifacts/aws-release-smoke.json")
a = p.parse_args()
if verify().get("status") != "passed":
    raise SystemExit("Skipped evaluation cannot be promoted as an approved baseline")
manifest = json.loads((ROOT / ".artifacts/release-manifest.json").read_text())
smoke = json.loads(Path(a.smoke).read_text())
required = [
    "live_aws",
    "live_cognito",
    "live_vercel",
    "browsing_workers_zero",
    "independent_admin_controls",
    "answer_fail_then_success",
    "index_fail_then_success",
    "models_reused",
    "idle_sixty_real_minutes",
    "minute_59_reset",
    "native_fargate_sizing",
    "rollback_smoke",
    "no_surprise_compute",
]
if smoke.get("release_id") != manifest["release_id"] or any(
    smoke.get(key) is not True for key in required
):
    raise SystemExit(
        "Real release acceptance evidence is incomplete; protected baseline unchanged"
    )
import boto3  # noqa: E402

s3 = boto3.client("s3")
report = (ROOT / ".artifacts/candidate-evaluation.json").read_bytes()
measured = None
configuration = (ROOT / "deployment/release-config.json").read_bytes()
if manifest["quality"].get("deployment_equivalence"):
    policy = json.loads(
        (ROOT / "deployment/product-quality-acceptance.json").read_text()
    )
    measured_id = policy["deployment_equivalence"]["measured_release_id"]
    measured = json.loads(
        s3.get_object(
            Bucket=a.bucket, Key="releases/" + measured_id + "/release-manifest.json"
        )["Body"].read()
    )
    if measured["release_id"] != measured_id:
        raise SystemExit("Archived measured release identity differs")
    configuration = s3.get_object(
        Bucket=a.bucket,
        Key="releases/" + measured_id + "/deployment/release-config.json",
    )["Body"].read()
production_id = manifest["release_id"]
manifest = select_reference(manifest, json.loads(report), configuration, measured)
key = "baselines/approved/" + production_id + "/evaluation.json"
manifest["report_key"] = key
s3.put_object(
    Bucket=a.bucket,
    Key=key,
    Body=report,
    ContentType="application/json",
    ServerSideEncryption="AES256",
    IfNoneMatch="*",
)
s3.put_object(
    Bucket=a.bucket,
    Key="baselines/approved/" + production_id + "/manifest.json",
    Body=json.dumps(manifest).encode(),
    ContentType="application/json",
    ServerSideEncryption="AES256",
    IfNoneMatch="*",
)
try:
    head = s3.head_object(Bucket=a.bucket, Key="baselines/current.json")
    condition = {"IfMatch": head["ETag"]}
except s3.exceptions.ClientError as exc:
    if exc.response["Error"]["Code"] not in {"404", "NoSuchKey", "NotFound"}:
        raise
    condition = {"IfNoneMatch": "*"}
s3.put_object(
    Bucket=a.bucket,
    Key="baselines/current.json",
    Body=json.dumps(manifest).encode(),
    ContentType="application/json",
    ServerSideEncryption="AES256",
    **condition,
)
print(
    "Approved measured quality reference promoted atomically after real smoke evidence; "
    "measurement and production identities remain separate"
)
