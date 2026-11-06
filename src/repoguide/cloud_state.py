"""Durable per-service control, transactional job accounting, leases and outbox.

Only start_service may increase ECS desired count. API callers supply identity
only after Gateway claims have been checked by cloud_api.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from functools import lru_cache

KINDS = ("answer", "index")
TERMINAL = {"complete", "failed", "cancelled"}


class Conflict(RuntimeError):
    pass


class JobCancelled(RuntimeError):
    pass


@lru_cache
def clients():
    import boto3
    from botocore.config import Config

    return tuple(
        boto3.client(
            s,
            config=Config(
                connect_timeout=2,
                read_timeout=25
                if s == "sqs" and os.getenv("REPOGUIDE_WORKER_KIND")
                else 4,
                retries={"max_attempts": 2},
            ),
        )
        for s in ("dynamodb", "sqs", "ecs")
    )


def table():
    return os.environ["REPOGUIDE_JOB_TABLE"]


def setting(kind, suffix):
    if kind not in KINDS:
        raise ValueError("Unknown worker kind")
    return os.environ[f"REPOGUIDE_{kind.upper()}_{suffix}"]


def encode(value):
    from boto3.dynamodb.types import TypeSerializer

    return {k: TypeSerializer().serialize(v) for k, v in value.items()}


def decode(value):
    from boto3.dynamodb.types import TypeDeserializer

    return {k: TypeDeserializer().deserialize(v) for k, v in value.items()}


def get(pk):
    return decode(
        clients()[0]
        .get_item(TableName=table(), Key=encode({"pk": pk}), ConsistentRead=True)
        .get("Item", {})
    )


def expression_names(expression, condition, names=None):
    names = dict(names or {})
    for attribute in ("percent", "error", "status", "result"):
        pattern = r"(?<![:#\w])" + attribute + r"\b"
        alias = "#" + attribute
        if re.search(pattern, expression + (condition or "")):
            expression = re.sub(pattern, alias, expression)
            condition = re.sub(pattern, alias, condition) if condition else condition
            names[alias] = attribute
    for alias, attribute in {"#s": "status", "#result": "result"}.items():
        if alias in expression or alias in (condition or ""):
            names[alias] = attribute
    return expression, condition, names


def update(pk, expression, values, condition=None, names=None):
    expression, condition, names = expression_names(expression, condition, names)
    args = dict(
        TableName=table(),
        Key=encode({"pk": pk}),
        UpdateExpression=expression,
        ExpressionAttributeValues=encode(values),
    )
    if condition:
        args["ConditionExpression"] = condition
    if names:
        args["ExpressionAttributeNames"] = names
    return clients()[0].update_item(**args)


def transaction(items):
    clients()[0].transact_write_items(TransactItems=items)


def tx_update(pk, expression, values, condition):
    expression, condition, names = expression_names(expression, condition)
    request = {
        "TableName": table(),
        "Key": encode({"pk": pk}),
        "UpdateExpression": expression,
        "ExpressionAttributeValues": encode(values),
        "ConditionExpression": condition,
    }
    if names:
        request["ExpressionAttributeNames"] = names
    return {"Update": request}


def control(kind):
    setting(kind, "SERVICE")
    return {
        "pk": "control#" + kind,
        "desired_state": "off",
        "observed_state": "stopped",
        "pending": 0,
        **get("control#" + kind),
    }


def acquire(kind):
    token = str(uuid.uuid4())
    try:
        update(
            "control#" + kind,
            "SET operation_token=:t, operation_until=:until",
            {":t": token, ":until": int(time.time()) + 45, ":now": int(time.time())},
            "attribute_not_exists(operation_token) OR operation_until<:now",
        )
    except Exception as exc:
        if (
            getattr(exc, "response", {}).get("Error", {}).get("Code")
            != "ConditionalCheckFailedException"
        ):
            raise
        raise Conflict(
            "Another control operation is in progress; retry shortly"
        ) from exc
    return token


def release(kind, token):
    update(
        "control#" + kind,
        "REMOVE operation_token, operation_until",
        {":t": token},
        "operation_token=:t",
    )


def start_service(kind, subject):
    token = acquire(kind)
    try:
        ctl = control(kind)
        if ctl.get("desired_state") == "on":
            return ctl
        service = clients()[2].describe_services(
            cluster=os.environ["REPOGUIDE_ECS_CLUSTER"],
            services=[setting(kind, "SERVICE")],
        )["services"][0]
        if (
            service["runningCount"]
            or service["pendingCount"]
            or ctl.get("desired_state") == "draining"
        ):
            raise Conflict("Worker is still stopping or draining")
        generation, now = str(uuid.uuid4()), int(time.time())
        update(
            "control#" + kind,
            "SET desired_state=:on, observed_state=:starting, generation=:g, start_requested_at=:now, started_by=:by, pending=if_not_exists(pending,:zero), startup_failures=:zero REMOVE idle_since, ready_at, worker_id, running_job, last_error",
            {
                ":on": "on",
                ":starting": "starting",
                ":g": generation,
                ":now": now,
                ":by": subject,
                ":zero": 0,
                ":t": token,
            },
            "operation_token=:t",
        )
        # This is the sole scale-up call in the application.
        try:
            clients()[2].update_service(
                cluster=os.environ["REPOGUIDE_ECS_CLUSTER"],
                service=setting(kind, "SERVICE"),
                desiredCount=1,
            )
        except Exception:
            update(
                "control#" + kind,
                "SET desired_state=:off, observed_state=:failed, last_error=:e",
                {
                    ":off": "off",
                    ":failed": "failed",
                    ":e": "ECS start rejected",
                    ":g": generation,
                },
                "generation=:g",
            )
            raise
        return control(kind)
    finally:
        release(kind, token)


def stop_service(kind, subject, force=False):
    token = acquire(kind)
    try:
        update(
            "control#" + kind,
            "SET desired_state=:drain, observed_state=:drain, stop_requested_at=:now, stopped_by=:by, force_stop=:force REMOVE idle_since",
            {
                ":drain": "draining",
                ":now": int(time.time()),
                ":by": subject,
                ":force": force,
                ":t": token,
            },
            "operation_token=:t",
        )
        return control(kind)
    finally:
        release(kind, token)


def queue_counts(kind):
    values = clients()[1].get_queue_attributes(
        QueueUrl=setting(kind, "QUEUE_URL"),
        AttributeNames=[
            "ApproximateNumberOfMessages",
            "ApproximateNumberOfMessagesNotVisible",
            "ApproximateNumberOfMessagesDelayed",
        ],
    )["Attributes"]
    return {
        "queued": int(values.get("ApproximateNumberOfMessages", 0)),
        "inflight": int(values.get("ApproximateNumberOfMessagesNotVisible", 0)),
        "delayed": int(values.get("ApproximateNumberOfMessagesDelayed", 0)),
    }


def status(kind):
    ctl = control(kind)
    public = {
        k: v
        for k, v in ctl.items()
        if k not in {"pk", "operation_token", "started_by", "stopped_by"}
    }
    return {
        **public,
        **queue_counts(kind),
        "kind": kind,
        "idle_stop_at": int(ctl["idle_since"]) + 3600
        if ctl.get("idle_since")
        else None,
    }


def publish_job(job):
    clients()[1].send_message(
        QueueUrl=setting(job["kind"], "QUEUE_URL"),
        MessageBody=json.dumps({"job_id": job["id"]}),
    )
    update(
        job["pk"],
        "SET dispatch_key=:active, dispatch_at=:created",
        {
            ":id": job["id"],
            ":active": "active#" + job["kind"],
            ":created": job["created_at"],
            ":queued": "queued",
            ":running": "running",
            ":retry": "retrying",
        },
        "id=:id AND #s IN (:queued,:running,:retry)",
    )


def submit(kind, subject, payload, idempotency_key):
    ctl = control(kind)
    if ctl.get("desired_state") != "on" or ctl.get("observed_state") not in {
        "starting",
        "loading",
        "ready",
    }:
        raise Conflict(
            f"{kind.title()} worker is offline; an administrator must start it"
        )
    request_hash = hashlib.sha256(
        json.dumps(
            {k: v for k, v in payload.items() if k != "remote_checked_at"},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    idempotency = hashlib.sha256(
        f"{kind}:{subject}:{idempotency_key}".encode()
    ).hexdigest()
    old = get("idempotency#" + idempotency)
    if old:
        if old["request_hash"] != request_hash:
            raise Conflict("Idempotency key already used for a different request")
        return public_job(old["job_id"], subject)
    now, job_id = int(time.time()), str(uuid.uuid4())
    job = {
        "pk": "job#" + job_id,
        "id": job_id,
        "kind": kind,
        "owner_sub": subject,
        "status": "queued",
        "stage": "queued",
        "detail": "Waiting for a ready worker",
        "percent": 0,
        "payload": json.dumps(payload),
        "created_at": now,
        "updated_at": now,
        "attempt": 0,
        "active_kind": kind,
        "active_at": now,
        "dispatch_key": "pending",
        "dispatch_at": now,
        "accounted": True,
    }
    if kind == "index":
        job.update(
            catalog_pk="user#" + subject, catalog_sk=f"job#index#{now:012d}#{job_id}"
        )
    items = [
        {
            "Put": {
                "TableName": table(),
                "Item": encode(job),
                "ConditionExpression": "attribute_not_exists(pk)",
            }
        },
        {
            "Put": {
                "TableName": table(),
                "Item": encode(
                    {
                        "pk": "idempotency#" + idempotency,
                        "job_id": job_id,
                        "request_hash": request_hash,
                        "expires_at": now + 86400,
                    }
                ),
                "ConditionExpression": "attribute_not_exists(pk)",
            }
        },
        tx_update(
            "useractive#" + kind + "#" + subject,
            "SET pending=if_not_exists(pending,:zero)+:one",
            {":zero": 0, ":one": 1, ":limit": 2},
            "attribute_not_exists(pending) OR pending<:limit",
        ),
        tx_update(
            "control#" + kind,
            "SET pending=if_not_exists(pending,:zero)+:one, last_job_at=:now REMOVE idle_since",
            {
                ":zero": 0,
                ":one": 1,
                ":now": now,
                ":g": ctl["generation"],
                ":on": "on",
                ":ready": "ready",
                ":starting": "starting",
                ":loading": "loading",
                ":limit": 20,
            },
            "generation=:g AND desired_state=:on AND observed_state IN (:ready,:starting,:loading) AND attribute_not_exists(operation_token) AND pending<:limit",
        ),
    ]
    if payload.get("conversation_id"):
        key = (
            "conversation#"
            + hashlib.sha256(subject.encode()).hexdigest()
            + "#"
            + str(uuid.UUID(payload["conversation_id"]))
        )
        items.append(
            tx_update(
                key,
                "SET active_job_id=:job",
                {":job": job_id, ":owner": subject, ":repo": payload["repo_id"]},
                "owner_sub=:owner AND repo_id=:repo AND attribute_not_exists(deleted)",
            )
        )
    transaction(items)
    try:
        publish_job(job)
    except Exception:
        pass  # Durable dispatch GSI is retried by the controller, never auto-starts ECS.
    return public_job(job_id, subject)


def public_job(job_id, subject=None):
    try:
        uuid.UUID(str(job_id))
    except ValueError:
        return None
    job = get("job#" + job_id)
    if not job or (subject is not None and job["owner_sub"] != subject):
        return None
    data = json.loads(job.get("payload", "{}"))
    if subject is not None and data.get("conversation_id"):
        key = (
            "conversation#"
            + hashlib.sha256(subject.encode()).hexdigest()
            + "#"
            + data["conversation_id"]
        )
        if get(key).get("deleted"):
            return None
    result = json.loads(job["result"]) if "result" in job else None
    if job.get("result_s3_key"):
        import boto3

        body = boto3.client("s3").get_object(
            Bucket=os.environ["REPOGUIDE_ARTIFACT_BUCKET"], Key=job["result_s3_key"]
        )["Body"]
        result = json.loads(body.read(2000000))
    keys = (
        "id",
        "kind",
        "status",
        "stage",
        "detail",
        "percent",
        "created_at",
        "updated_at",
        "attempt",
        "error_code",
    )
    return {
        **{k: job.get(k) for k in keys},
        "result": result,
        "events": job.get("events", []),
        "cancel_requested": bool(job.get("cancel_requested")),
        **(
            {"repository_url": data.get("url"), "branch": data.get("branch")}
            if job["kind"] == "index"
            else {}
        ),
        "error": {
            "QueueExpired": "This job waited too long while compute was stopped. Submit it again when the worker is running.",
            "Cancelled": "Generation stopped. Your question is saved.",
            "TimeoutError": "The request timed out. Your question is saved; try a narrower question.",
            "InvalidGeneration": "The model response could not be verified. Try the question again.",
            "ValueError": "The request could not be processed. Check the repository limits or try a more specific question.",
        }.get(
            job.get("error_code"),
            "This request failed. Your saved question can be retried."
            if job.get("error_code")
            else None,
        ),
    }


def claim(job, kind, generation, worker_id):
    now, lease = int(time.time()), str(uuid.uuid4())
    claim_item = tx_update(
        job["pk"],
        "SET lease_token=:lease, lease_until=:until, lease_generation=:g, worker_id=:w, #s=:running, stage=:running, updated_at=:now, attempt=attempt+:one",
        {
            ":lease": lease,
            ":until": now + 180,
            ":g": generation,
            ":w": worker_id,
            ":running": "running",
            ":queued": "queued",
            ":retry": "retrying",
            ":now": now,
            ":one": 1,
            ":kind": kind,
        },
        "kind=:kind AND (#s IN (:queued,:retry) OR (#s=:running AND lease_until<:now))",
    )
    transaction(
        [
            claim_item,
            tx_update(
                "control#" + kind,
                "SET running_job=:job REMOVE idle_since",
                {
                    ":job": job["id"],
                    ":g": generation,
                    ":w": worker_id,
                    ":on": "on",
                    ":ready": "ready",
                },
                "generation=:g AND worker_id=:w AND desired_state=:on AND observed_state=:ready AND attribute_not_exists(operation_token) AND (attribute_not_exists(running_job) OR running_job=:job)",
            ),
        ]
    )
    return lease


def progress(job_id, lease, stage, percent, detail):
    current = get("job#" + job_id)
    events = current.get("events", [])
    if not events or events[-1]["stage"] != stage:
        events = (
            events
            + [
                {
                    "stage": stage,
                    "time": int(time.time() * 1000),
                    "detail": detail[:160],
                }
            ]
        )[-40:]
    update(
        "job#" + job_id,
        "SET stage=:stage, percent=:p, detail=:d, updated_at=:now, lease_until=:until, events=:events",
        {
            ":stage": stage,
            ":p": int(percent),
            ":d": detail[:200],
            ":now": int(time.time()),
            ":until": int(time.time()) + 180,
            ":lease": lease,
            ":running": "running",
            ":events": events,
        },
        "lease_token=:lease AND #s=:running",
        {"#s": "status"},
    )


def chat_delivery(job, now):
    data = json.loads(job.get("payload", "{}"))
    if not data.get("conversation_id"):
        return None
    return {
        "pk": "chat-delivery#" + job["id"],
        "catalog_pk": "chat-deliveries",
        "catalog_sk": f"delivery#{now:012d}#{job['id']}",
        "job_id": job["id"],
        "owner_sub": job["owner_sub"],
        "conversation_id": str(uuid.UUID(data["conversation_id"])),
        "turn_id": str(uuid.UUID(data["turn_id"])),
    }


def finish(job, lease, generation, state, *, result=None, error=None):
    now = int(time.time())
    delivery = chat_delivery(job, now)
    values = {
        ":state": state,
        ":now": now,
        ":ttl": now + 7 * 86400,
        ":lease": lease,
        ":running": "running",
        ":error": error or "",
        ":detail": "Complete" if state == "complete" else "Job failed",
        ":p": 100 if state == "complete" else 0,
    }
    expression = "SET #s=:state, stage=:state, updated_at=:now, expires_at=:ttl, error_code=:error, detail=:detail, percent=:p"
    if delivery:
        expression = expression.replace(", expires_at=:ttl", "")
        values.pop(":ttl")
    if result is not None:
        raw = json.dumps(result, default=str, separators=(",", ":"))
        if len(raw.encode()) < 200000:
            values[":result"] = raw
            expression += ", #result=:result"
        else:
            import boto3

            key = "jobs/" + job["id"] + "/" + lease + ".json"
            if delivery:
                key = f"conversations/{hashlib.sha256(job['owner_sub'].encode()).hexdigest()}/{delivery['conversation_id']}/results/{job['id']}-{lease}.json"
            boto3.client("s3").put_object(
                Bucket=os.environ["REPOGUIDE_ARTIFACT_BUCKET"],
                Key=key,
                Body=raw.encode(),
                ContentType="application/json",
                ServerSideEncryption="AES256",
            )
            values[":result"] = key
            expression += ", result_s3_key=:result"
    expression += (
        " REMOVE active_kind, active_at, lease_until, dispatch_key, dispatch_at"
    )
    if delivery:
        expression += ", expires_at"
    a = tx_update(job["pk"], expression, values, "lease_token=:lease AND #s=:running")
    b = tx_update(
        "control#" + job["kind"],
        "SET pending=pending-:one, last_job_at=:now, last_job_completed_at=:now REMOVE running_job, idle_since",
        {":one": 1, ":now": now, ":g": generation, ":job": job["id"]},
        "generation=:g AND pending>=:one AND running_job=:job",
    )
    items = [a, b]
    if delivery:
        items.append({"Put": {"TableName": table(), "Item": encode(delivery)}})
    if job.get("accounted"):
        items.append(
            tx_update(
                "useractive#" + job["kind"] + "#" + job["owner_sub"],
                "SET pending=pending-:one",
                {":one": 1},
                "pending>=:one",
            )
        )
    transaction(items)


def cancel_job(job_id, subject, *, reason="Cancelled"):
    job = get("job#" + str(uuid.UUID(str(job_id))))
    if not job or job.get("owner_sub") != subject:
        raise LookupError("Job not found")
    if job["status"] in TERMINAL:
        return public_job(job_id, subject)
    if job["status"] == "running":
        update(
            job["pk"],
            "SET cancel_requested=:yes",
            {":yes": True, ":running": "running"},
            "#s=:running",
        )
    else:
        now = int(time.time())
        items = [
            tx_update(
                job["pk"],
                "SET #s=:cancelled, stage=:cancelled, updated_at=:now, expires_at=:ttl, error_code=:reason REMOVE active_kind, active_at, dispatch_key, dispatch_at",
                {
                    ":cancelled": "cancelled",
                    ":queued": "queued",
                    ":retry": "retrying",
                    ":now": now,
                    ":ttl": now + 7 * 86400,
                    ":reason": reason,
                },
                "#s IN (:queued,:retry)",
            ),
            tx_update(
                "control#" + job["kind"],
                "SET pending=pending-:one, last_job_completed_at=:now",
                {":one": 1, ":now": now},
                "pending>=:one",
            ),
        ]
        if job.get("accounted"):
            items.append(
                tx_update(
                    "useractive#" + job["kind"] + "#" + subject,
                    "SET pending=pending-:one",
                    {":one": 1},
                    "pending>=:one",
                )
            )
        delivery = chat_delivery(job, now)
        if delivery:
            request = items[0]["Update"]
            request["UpdateExpression"] = (
                request["UpdateExpression"].replace(", expires_at=:ttl", "")
                + ", expires_at"
            )
            request["ExpressionAttributeValues"].pop(":ttl")
            items.append({"Put": {"TableName": table(), "Item": encode(delivery)}})
        transaction(items)
    return public_job(job_id, subject)


def retry(job, lease, generation, error):
    a = tx_update(
        job["pk"],
        "SET #s=:retry, stage=:retry, error_code=:error, updated_at=:now REMOVE lease_until",
        {
            ":retry": "retrying",
            ":error": error,
            ":now": int(time.time()),
            ":lease": lease,
            ":running": "running",
        },
        "lease_token=:lease AND #s=:running",
    )
    b = tx_update(
        "control#" + job["kind"],
        "REMOVE running_job, idle_since",
        {":g": generation, ":job": job["id"]},
        "generation=:g AND running_job=:job",
    )
    transaction([a, b])


def worker_state(kind, generation, worker_id, observed, **extra):
    now = int(time.time())
    values = {
        ":g": generation,
        ":w": worker_id,
        ":now": now,
        ":observed": observed,
        ":on": "on",
        ":draining": "draining",
    }
    expression = "SET worker_id=:w, last_heartbeat=:now, observed_state=:observed"
    if observed == "ready":
        expression += ", ready_at=if_not_exists(ready_at,:now)"
    for k, v in extra.items():
        expression += f", {k}=:{k}"
        values[":" + k] = v
    values[":stale"] = now - 120
    update(
        "control#" + kind,
        expression,
        values,
        "generation=:g AND desired_state IN (:on,:draining) AND (attribute_not_exists(worker_id) OR worker_id=:w OR last_heartbeat<:stale)",
    )


def fail_queued_delivery(job):
    """Reconcile native SQS redrive so a queued row cannot pin compute forever."""
    now = int(time.time())
    items = [
        tx_update(
            job["pk"],
            "SET #s=:failed, stage=:failed, error_code=:error, detail=:detail, percent=:zero, updated_at=:now, expires_at=:ttl REMOVE dispatch_key, dispatch_at, lease_until, active_kind, active_at",
            {
                ":failed": "failed",
                ":error": "DLQExhausted",
                ":detail": "Delivery exhausted; inspect the dead-letter queue",
                ":zero": 0,
                ":now": now,
                ":ttl": now + 7 * 86400,
                ":queued": "queued",
                ":retry": "retrying",
            },
            "#s IN (:queued,:retry)",
        ),
        tx_update(
            "control#" + job["kind"],
            "SET pending=pending-:one, last_job_at=:now, last_job_completed_at=:now REMOVE idle_since",
            {":one": 1, ":now": now},
            "pending>=:one",
        ),
    ]
    if job.get("accounted"):
        items.append(
            tx_update(
                "useractive#" + job["kind"] + "#" + job["owner_sub"],
                "SET pending=pending-:one",
                {":one": 1},
                "pending>=:one",
            )
        )
    transaction(items)
