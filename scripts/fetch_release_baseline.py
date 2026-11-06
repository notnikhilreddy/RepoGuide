"""Read the protected approved baseline; never create or reset it."""

import argparse
import json
import os
from pathlib import Path

import boto3

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--bucket", default=os.getenv("RELEASE_BUCKET"))
a = p.parse_args()
if not a.bucket:
    raise SystemExit("Protected release bucket is required")
s3 = boto3.client("s3")
manifest = json.loads(
    s3.get_object(Bucket=a.bucket, Key="baselines/current.json")["Body"].read(100000)
)
key = manifest.get("report_key", "")
if not key.startswith("baselines/approved/") or not key.endswith("/evaluation.json"):
    raise SystemExit("Protected pointer has an invalid report reference")
report = s3.get_object(Bucket=a.bucket, Key=key)["Body"].read(5000000)
artifacts = Path(".artifacts")
artifacts.mkdir(exist_ok=True)
(artifacts / "approved-baseline.json").write_text(json.dumps(manifest, indent=2))
(artifacts / "approved-evaluation.json").write_bytes(report)
print("Protected approved baseline and measured report fetched; pointer unchanged")
