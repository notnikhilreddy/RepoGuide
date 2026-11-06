"""Archive and remove only diagnostics for explicitly recorded deployment tests.

Never purges a queue or removes unknown messages. Durable failed job rows remain.
Long polling allows the controller's inspection visibility leases to expire.
"""

import fcntl
import json
import subprocess
import time
from pathlib import Path

import boto3

root = Path(__file__).resolve().parents[1]
art = root / ".artifacts"
lock = (art / "smoke-dlq-cleanup.lock").open("a")
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit("Another deployment diagnostic archiver is running") from None
out = {
    k: v["value"]
    for k, v in json.loads(
        subprocess.check_output(
            ["terraform", "-chdir=" + str(root / "infra/terraform"), "output", "-json"]
        )
    ).items()
}
expected = {"answer": set(), "index": set()}
for path in [art / "aws-final-smoke.json", *sorted((art / "failures").glob("*.json"))]:
    report = json.loads(path.read_text())
    for kind, job_id in report.get("failed_test_job_ids", {}).items():
        expected[kind].add(job_id)
session = boto3.Session(profile_name="repoguide", region_name="us-east-2")
sqs = session.client("sqs")
s3 = session.client("s3")
table = session.resource("dynamodb").Table(out["job_table"])
report = {
    "only_recorded_test_jobs": True,
    "diagnostics": [],
    "removed": [],
    "unknown_returned": 0,
}
previous_receipt = art / "smoke-dlq-cleanup.json"
if previous_receipt.exists():
    previous = json.loads(previous_receipt.read_text())
    report["diagnostics"] = previous.get("diagnostics", [])
    report["removed"] = previous.get("removed", [])
    for item in report["diagnostics"]:
        expected[item["kind"]].add(item["job_id"])
remaining = {kind: set(ids) - set(report["removed"]) for kind, ids in expected.items()}
deadline = time.monotonic() + 660
while any(remaining.values()) and time.monotonic() < deadline:
    for kind, ids in remaining.items():
        if not ids:
            continue
        queue = out["deadletter_queues"][kind]
        messages = sqs.receive_message(
            QueueUrl=queue,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=20,
            VisibilityTimeout=60,
        ).get("Messages", [])
        for message in messages:
            data = json.loads(message["Body"])
            job_id = data.get("job_id")
            if job_id not in ids:
                sqs.change_message_visibility(
                    QueueUrl=queue,
                    ReceiptHandle=message["ReceiptHandle"],
                    VisibilityTimeout=0,
                )
                report["unknown_returned"] += 1
                continue
            durable = table.get_item(Key={"pk": "job#" + job_id}, ConsistentRead=True)[
                "Item"
            ]
            assert durable["status"] == "failed" and durable["kind"] == kind
            diagnostic = {
                "kind": kind,
                "job_id": job_id,
                "error_type": data.get("error_type"),
                "durable_status": "failed",
            }
            key = "diagnostics/deployment-smoke/" + job_id + ".json"
            saved = s3.put_object(
                Bucket=out["artifact_bucket"],
                Key=key,
                Body=json.dumps(diagnostic).encode(),
                ContentType="application/json",
                ServerSideEncryption="AES256",
            )
            assert saved.get("VersionId")
            report["diagnostics"].append(
                {
                    **diagnostic,
                    "archive_key": key,
                    "archive_version": saved["VersionId"],
                }
            )
            (art / "smoke-dlq-cleanup.json").write_text(json.dumps(report, indent=2))
            sqs.delete_message(QueueUrl=queue, ReceiptHandle=message["ReceiptHandle"])
            ids.remove(job_id)
            report["removed"].append(job_id)
report["passed"] = not any(remaining.values())
report["expected_diagnostics"] = sum(len(ids) for ids in expected.values())
(art / "smoke-dlq-cleanup.json").write_text(json.dumps(report, indent=2))
assert report["passed"], (
    "Some recorded test diagnostics are still waiting for inspection visibility expiry"
)
print(
    json.dumps(
        {
            "passed": True,
            "archived_and_removed": len(report["removed"]),
            "durable_jobs_preserved": True,
        }
    )
)
