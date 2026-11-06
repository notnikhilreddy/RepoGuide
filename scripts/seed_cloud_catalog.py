"""Seed real evaluation datasets into an existing private artifact bucket.

Does not run evaluation or manufacture reports/scores. Existing report entries
are preserved. Preview is the default; --apply writes versioned S3 objects.
"""

import argparse
import json
import subprocess
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--apply", action="store_true")
args = parser.parse_args()
out = json.loads(
    subprocess.check_output(
        ["terraform", "-chdir=" + str(root / "infra/terraform"), "output", "-json"],
        text=True,
    )
)
bucket = out["artifact_bucket"]["value"]
s3 = boto3.Session(profile_name="repoguide", region_name="us-east-2").client("s3")
try:
    previous = json.loads(
        s3.get_object(Bucket=bucket, Key="evaluations/catalog.json")["Body"].read()
    )
except ClientError as exc:
    if exc.response["Error"]["Code"] not in {"NoSuchKey", "404"}:
        raise
    previous = {"datasets": [], "reports": []}
dataset = root / "evals/release_cases.json"
data = json.loads(dataset.read_bytes())
cases = data if isinstance(data, list) else data["cases"]
entry = {"name": dataset.name, "cases": len(cases)}
catalog = {
    **previous,
    "datasets": [d for d in previous.get("datasets", []) if d["name"] != dataset.name]
    + [entry],
}
if not catalog.get("reports"):
    catalog["quality_status"] = "skipped_by_owner"
if args.apply:
    for key, content in [
        ("evaluations/datasets/" + dataset.name, dataset.read_bytes()),
        ("evaluations/catalog.json", json.dumps(catalog).encode()),
    ]:
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=content,
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )
print(
    json.dumps(
        {
            "applied": args.apply,
            "dataset": entry,
            "report_count": len(catalog.get("reports", [])),
        }
    )
)
