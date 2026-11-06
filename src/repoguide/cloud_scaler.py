"""Scale-down-only reconciler. Queue backlog can never enable compute."""

from __future__ import annotations

import json
import logging
import os
import time

from repoguide import cloud_state as state

log = logging.getLogger(__name__)


def idle_action(control, queues, now):
    intent = control.get("desired_state", "off")
    if intent == "off":
        return "stop"
    if intent == "draining":
        if (
            control.get("running_job")
            and not control.get("force_stop")
            and now - int(control.get("stop_requested_at", now)) < 900
        ):
            return "wait"
        return "stop"
    observed = control.get("observed_state")
    if observed in {"starting", "loading"}:
        if int(control.get("startup_failures", 0)) >= 3:
            return "fail"
        return (
            "fail"
            if now - int(control.get("start_requested_at", now)) >= 1200
            else "wait"
        )
    if observed != "ready":
        return "fail"
    if now - int(control.get("last_heartbeat", now)) >= 180:
        return "fail"
    if (
        int(control.get("pending", 0)) > 0
        or control.get("running_job")
        or sum(queues.values()) > 0
    ):
        return "busy"
    since = control.get("idle_since")
    if since is None:
        return "begin_idle"
    return "stop" if now - int(since) >= 3600 else "wait"


def dispatch_outbox():
    db = state.clients()[0]
    rows = db.query(
        TableName=state.table(),
        IndexName="dispatch",
        KeyConditionExpression="dispatch_key=:pending",
        ExpressionAttributeValues=state.encode({":pending": "pending"}),
        Limit=100,
    ).get("Items", [])
    for raw in rows:
        job = state.get(state.decode(raw)["pk"])
        if job.get("dispatch_key") and job.get("status") not in state.TERMINAL:
            try:
                state.publish_job(job)
            except Exception as exc:
                log.error(
                    json.dumps(
                        {
                            "event": "outbox_retry",
                            "job_id": job["id"],
                            "error_type": type(exc).__name__,
                        }
                    )
                )


def reconcile_dead_letters(kind):
    messages = (
        state.clients()[1]
        .receive_message(
            QueueUrl=state.setting(kind, "DLQ_URL"),
            MaxNumberOfMessages=10,
            WaitTimeSeconds=0,
            VisibilityTimeout=300,
        )
        .get("Messages", [])
    )
    for message in messages:
        try:
            data = json.loads(message["Body"])
            job_id = data.get("job_id")
            if not isinstance(job_id, str):
                continue
            job = state.get("job#" + job_id)
            if job.get("kind") == kind and job.get("status") in {"queued", "retrying"}:
                state.fail_queued_delivery(job)
        except (ValueError, TypeError, KeyError):
            continue
    # Deliberately retain DLQ messages for inspection/alarms. DLQ depth is not
    # considered active work and can never start or keep a service enabled.


def reconcile(kind, now=None):
    now = int(time.time()) if now is None else now
    token = state.acquire(kind)
    try:
        # Published rows remain in the existing sparse dispatch index until
        # terminal. Queue expiry or a long manual stop cannot leak quota forever.
        expired = (
            state.clients()[0]
            .query(
                TableName=state.table(),
                IndexName="dispatch",
                KeyConditionExpression="dispatch_key=:kind AND dispatch_at<:before",
                ExpressionAttributeValues=state.encode(
                    {":kind": "active#" + kind, ":before": now - 86400}
                ),
                Limit=20,
            )
            .get("Items", [])
        )
        for raw in expired:
            queued = state.get(state.decode(raw)["pk"])
            if queued.get("status") in {"queued", "retrying"}:
                state.cancel_job(
                    queued["id"], queued["owner_sub"], reason="QueueExpired"
                )
        ctl = state.control(kind)
        # A process can die after claiming a job. Recover its durable lease even
        # if repeated receives have already exhausted SQS redrive attempts.
        if ctl.get("running_job"):
            job = state.get("job#" + ctl["running_job"])
            if (
                job.get("status") == "running"
                and int(job.get("lease_until", now)) < now - 180
            ):
                if int(job.get("attempt", 0)) >= 3:
                    state.finish(
                        job,
                        job["lease_token"],
                        ctl["generation"],
                        "failed",
                        error="LeaseExpired",
                    )
                else:
                    state.retry(
                        job, job["lease_token"], ctl["generation"], "LeaseExpired"
                    )
                    state.update(
                        job["pk"],
                        "SET dispatch_key=:pending, dispatch_at=:now",
                        {":pending": "pending", ":now": now},
                    )
                ctl = state.control(kind)
        reconcile_dead_letters(kind)
        ctl = state.control(kind)
        queues = state.queue_counts(kind)
        action = idle_action(ctl, queues, now)
        service = state.clients()[2].describe_services(
            cluster=os.environ["REPOGUIDE_ECS_CLUSTER"],
            services=[state.setting(kind, "SERVICE")],
        )["services"][0]
        if ctl.get("desired_state") == "on" and service["desiredCount"] == 0:
            action = "fail"  # Never recreate a manually stopped service from a timer.
        values = {":t": token}
        if action == "begin_idle":
            state.update(
                "control#" + kind,
                "SET idle_since=:now",
                {**values, ":now": now, ":zero": 0},
                "operation_token=:t AND pending=:zero AND attribute_not_exists(running_job)",
            )
        elif action == "busy":
            state.update(
                "control#" + kind, "REMOVE idle_since", values, "operation_token=:t"
            )
        elif action in {"stop", "fail"}:
            # Durable accounting and the queue sample were read while acceptance
            # and new claims are fenced by operation_token. Existing work may only
            # finish, never appear behind this check.
            if ctl.get("running_job"):
                job = state.get("job#" + ctl["running_job"])
                if job and job.get("status") == "running":
                    state.retry(
                        job,
                        job["lease_token"],
                        ctl["generation"],
                        "Interrupted by explicit stop or worker failure",
                    )
            observed = (
                "failed"
                if action == "fail" or ctl.get("observed_state") == "failed"
                else (
                    "stopping"
                    if service["runningCount"] or service["pendingCount"]
                    else "stopped"
                )
            )
            state.update(
                "control#" + kind,
                "SET desired_state=:off, observed_state=:observed REMOVE idle_since, running_job",
                {**values, ":off": "off", ":observed": observed},
                "operation_token=:t",
            )
            if service["desiredCount"] != 0:
                state.clients()[2].update_service(
                    cluster=os.environ["REPOGUIDE_ECS_CLUSTER"],
                    service=state.setting(kind, "SERVICE"),
                    desiredCount=0,
                )
        return {
            "kind": kind,
            "action": action,
            "pending": int(ctl.get("pending", 0)),
            **queues,
        }
    finally:
        state.release(kind, token)


def handler(event, context):
    dispatch_outbox()
    results = []
    for kind in state.KINDS:
        try:
            results.append(reconcile(kind))
        except state.Conflict:
            results.append({"kind": kind, "action": "control_busy"})
        except Exception as exc:
            log.error(json.dumps({"kind": kind, "error_type": type(exc).__name__}))
            raise
    try:
        from repoguide.cloud_product import retry_chat_deliveries

        retry_chat_deliveries()
    except Exception as exc:
        log.warning(
            json.dumps(
                {
                    "event": "chat_delivery_retry_pending",
                    "error_type": type(exc).__name__,
                }
            )
        )
    return results
