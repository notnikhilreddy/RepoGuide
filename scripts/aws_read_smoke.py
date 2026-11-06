"""Probe actual Neon resume and warmed API reads without changing worker idleness.

Wait seven minutes after other browsing stops before running with --resume.
This makes no job submissions and spends no model tokens.
"""

import argparse
import json
import subprocess
import time
from pathlib import Path

import boto3
import httpx

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--resume", action="store_true")
args = parser.parse_args()
out = {
    k: v["value"]
    for k, v in json.loads(
        subprocess.check_output(
            ["terraform", "-chdir=" + str(root / "infra/terraform"), "output", "-json"],
            text=True,
        )
    ).items()
}
credentials = json.loads((root / ".artifacts/private/cognito-admin.json").read_text())
identity = boto3.Session(profile_name="repoguide", region_name="us-east-2").client(
    "cognito-idp"
)
token = identity.admin_initiate_auth(
    UserPoolId=out["user_pool_id"],
    ClientId=out["cognito_client_id"],
    AuthFlow="ADMIN_USER_PASSWORD_AUTH",
    AuthParameters={
        "USERNAME": credentials["username"],
        "PASSWORD": credentials["password"],
    },
)["AuthenticationResult"]["AccessToken"]
report = {
    "live_aws": True,
    "live_neon": True,
    "jobs_submitted": 0,
    "resume_probe": args.resume,
}
with httpx.Client(
    base_url=out["api_url"],
    headers={"Authorization": "Bearer " + token},
    timeout=20,
) as http:
    before = http.get("/api/compute/status")
    before.raise_for_status()
    before = before.json()["workers"]
    started = time.monotonic()
    first = http.get("/api/ui/repositories")
    first.raise_for_status()
    report["first_list_seconds"] = round(time.monotonic() - started, 4)
    assert any("notnikhilreddy/RepoGuide" in r["url"] for r in first.json())
    samples = []
    for _ in range(10):
        started = time.monotonic()
        response = http.get("/api/ui/repositories")
        response.raise_for_status()
        assert response.json() == first.json()
        samples.append(round(time.monotonic() - started, 4))
    after = http.get("/api/compute/status")
    after.raise_for_status()
    after = after.json()["workers"]
    fields = ["desired_state", "idle_since", "pending", "worker_id"]
    for kind in ["answer", "index"]:
        assert all(before[kind].get(k) == after[kind].get(k) for k in fields)
    report.update(
        passed=True,
        worker_idle_fields_unchanged=True,
        first_read_excluded_from_warm_samples=True,
        warm_samples_seconds=samples,
        warm_p50_seconds=sorted(samples)[4],
        warm_p95_seconds=sorted(samples)[9],
    )
path = (
    root
    / ".artifacts"
    / ("aws-neon-resume.json" if args.resume else "native-api-benchmark.json")
)
path.write_text(json.dumps(report, indent=2))
print(json.dumps({k: v for k, v in report.items() if k != "warm_samples_seconds"}))
