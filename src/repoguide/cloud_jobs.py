"""Durable SQS jobs + DynamoDB state for the AWS deployment.
All state is persisted; nothing depends on Lambda in-memory threads.
"""

from __future__ import annotations

import os
import time
import uuid
from functools import lru_cache

from repoguide.git_utils import parse_github_url


def enabled() -> bool:
    return os.getenv("REPOGUIDE_CLOUD_MODE", "").lower() == "true"


@lru_cache
def clients():
    import boto3

    return (boto3.client("dynamodb"), boto3.client("sqs"), boto3.client("ecs"))


def _table():
    return os.environ["REPOGUIDE_JOB_TABLE"]


def _queue():
    return os.environ["REPOGUIDE_QUEUE_URL"]


def worker_paused() -> bool:
    ddb, _, _ = clients()
    r = ddb.get_item(
        TableName=_table(), Key={"pk": {"S": "control#worker"}}, ConsistentRead=True
    )
    return r.get("Item", {}).get("paused", {}).get("BOOL", False)


def update_job(
    job_id: str,
    *,
    status: str,
    stage: str,
    percent: int,
    detail: str,
    result: dict | None = None,
):
    ddb, _, _ = clients()
    now = int(time.time())
    values = {
        ":status": {"S": status},
        ":stage": {"S": stage},
        ":percent": {"N": str(max(0, min(percent, 100)))},
        ":detail": {"S": detail[:250]},
        ":updated": {"N": str(now)},
    }
    update = "SET #s=:status, stage=:stage, percent=:percent, detail=:detail, updated_at=:updated"
    if result is not None:
        import json

        values[":result"] = {"S": json.dumps(result, separators=(",", ":"))}
        update += ", result=:result"
    ddb.update_item(
        TableName=_table(),
        Key={"pk": {"S": "job#" + job_id}},
        UpdateExpression=update,
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues=values,
    )


def enqueue_index(url: str, force: bool = False, owner_sub: str = "") -> dict:
    owner, repo = parse_github_url(url)
    if worker_paused():
        raise RuntimeError("Workers are paused; indexing is temporarily disabled")
    ddb, sqs, ecs = clients()
    job_id = str(uuid.uuid4())
    canonical = f"https://github.com/{owner}/{repo}"
    now = int(time.time())
    ddb.put_item(
        TableName=_table(),
        Item={
            "pk": {"S": "job#" + job_id},
            "id": {"S": job_id},
            "kind": {"S": "index"},
            "owner_sub": {"S": owner_sub},
            "status": {"S": "queued"},
            "stage": {"S": "queued"},
            "percent": {"N": "0"},
            "detail": {"S": "Waiting for an ECS worker"},
            "url": {"S": canonical},
            "created_at": {"N": str(now)},
            "updated_at": {"N": str(now)},
            "expires_at": {"N": str(now + 7 * 86400)},
        },
        ConditionExpression="attribute_not_exists(pk)",
    )
    import json

    sqs.send_message(
        QueueUrl=_queue(),
        MessageBody=json.dumps(
            {"job_id": job_id, "kind": "index", "url": canonical, "force": bool(force)},
            separators=(",", ":"),
        ),
    )
    cluster = os.environ["REPOGUIDE_ECS_CLUSTER"]
    service = os.environ["REPOGUIDE_ECS_SERVICE"]
    # Idempotently wake the polling service. The 5-minute scaler handles scale-in.
    result = ecs.describe_services(cluster=cluster, services=[service])
    if not result.get("services"):
        raise RuntimeError(
            "ECS worker service unavailable; queued job will remain retryable"
        )
    if result["services"][0]["desiredCount"] == 0:
        ecs.update_service(cluster=cluster, service=service, desiredCount=1)
    return get_job(job_id)


def get_job(job_id: str, owner_sub: str | None = None) -> dict | None:
    if not isinstance(job_id, str):
        return None
    try:
        uuid.UUID(job_id)
    except ValueError:
        return None
    ddb, _, _ = clients()
    r = ddb.get_item(
        TableName=_table(), Key={"pk": {"S": "job#" + job_id}}, ConsistentRead=True
    )
    item = r.get("Item")
    if not item:
        return None
    if owner_sub is not None and item.get("owner_sub", {}).get("S") != owner_sub:
        return None
    import json

    result = json.loads(item["result"]["S"]) if "result" in item else None
    return {
        "id": item["id"]["S"],
        "kind": item["kind"]["S"],
        "status": item["status"]["S"],
        "stage": item["stage"]["S"],
        "percent": int(item["percent"]["N"]),
        "detail": item["detail"]["S"],
        "created_at": int(item["created_at"]["N"]),
        "updated_at": int(item["updated_at"]["N"]),
        "result": result,
        "error": None,
        "events": [],
    }


def worker_status() -> dict:
    ddb, sqs, ecs = clients()
    attrs = sqs.get_queue_attributes(
        QueueUrl=_queue(),
        AttributeNames=[
            "ApproximateNumberOfMessages",
            "ApproximateNumberOfMessagesNotVisible",
        ],
    )["Attributes"]
    services = ecs.describe_services(
        cluster=os.environ["REPOGUIDE_ECS_CLUSTER"],
        services=[os.environ["REPOGUIDE_ECS_SERVICE"]],
    )["services"]
    return {
        "paused": worker_paused(),
        "desired": services[0]["desiredCount"],
        "running": services[0]["runningCount"],
        "queued": int(attrs.get("ApproximateNumberOfMessages", "0")),
        "inflight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", "0")),
    }


def control_worker(action: str) -> dict:
    if action not in ("wake", "sleep"):
        raise ValueError("Unknown control action")
    status = worker_status()
    if action == "sleep" and (status["queued"] or status["inflight"]):
        raise RuntimeError("Cannot stop worker while jobs are pending or running")
    ddb, _, ecs = clients()
    ddb.update_item(
        TableName=_table(),
        Key={"pk": {"S": "control#worker"}},
        UpdateExpression="SET paused=:p, idle_checks=:z",
        ExpressionAttributeValues={":p": {"BOOL": action == "sleep"}, ":z": {"N": "0"}},
    )
    ecs.update_service(
        cluster=os.environ["REPOGUIDE_ECS_CLUSTER"],
        service=os.environ["REPOGUIDE_ECS_SERVICE"],
        desiredCount=0 if action == "sleep" else 1,
    )
    return worker_status()
