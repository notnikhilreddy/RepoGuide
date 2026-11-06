"""Promote measured baseline only after complete, real post-deploy evidence.

No waiver/skip switch. Owner-skipped quality evaluation cannot create an
approved baseline even when real functional AWS acceptance succeeds.
"""

import argparse
import json
from pathlib import Path

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
key = "baselines/approved/" + manifest["release_id"] + "/evaluation.json"
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
    Key="baselines/approved/" + manifest["release_id"] + "/manifest.json",
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
print("Approved baseline promoted atomically after real smoke evidence")
