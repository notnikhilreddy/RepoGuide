"""Contract tests against Moto's transactional DynamoDB and SQS implementations."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_aws

from repoguide import cloud_api as api
from repoguide import cloud_scaler as scaler
from repoguide import cloud_state as state
from repoguide import cloud_worker as worker


@pytest.fixture
def cloud(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    monkeypatch.setenv("REPOGUIDE_JOB_TABLE", "test-jobs")
    monkeypatch.setenv("REPOGUIDE_ECS_CLUSTER", "test-cluster")
    monkeypatch.setenv("REPOGUIDE_COGNITO_ISSUER", "https://issuer")
    monkeypatch.setenv("REPOGUIDE_COGNITO_CLIENT_ID", "client")
    with mock_aws():
        db, sqs = boto3.client("dynamodb"), boto3.client("sqs")
        db.create_table(
            TableName="test-jobs",
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "dispatch_key", "AttributeType": "S"},
                {"AttributeName": "dispatch_at", "AttributeType": "N"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "dispatch",
                    "KeySchema": [
                        {"AttributeName": "dispatch_key", "KeyType": "HASH"},
                        {"AttributeName": "dispatch_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "KEYS_ONLY"},
                }
            ],
        )
        services = {}
        ecs = MagicMock()
        for kind in state.KINDS:
            for suffix in ["QUEUE_URL", "DLQ_URL"]:
                url = sqs.create_queue(QueueName=kind + suffix)["QueueUrl"]
                monkeypatch.setenv("REPOGUIDE_" + kind.upper() + "_" + suffix, url)
            monkeypatch.setenv("REPOGUIDE_" + kind.upper() + "_SERVICE", kind)
            services[kind] = {"desiredCount": 0, "runningCount": 0, "pendingCount": 0}
        ecs.describe_services.side_effect = lambda **kw: {
            "services": [services[kw["services"][0]]]
        }
        ecs.update_service.side_effect = lambda **kw: services[kw["service"]].update(
            desiredCount=kw["desiredCount"]
        )
        monkeypatch.setattr(state, "clients", lambda: (db, sqs, ecs))
        yield db, sqs, ecs


def ready(kind="answer"):
    ctl = state.start_service(kind, "admin")
    state.worker_state(kind, ctl["generation"], "process-1", "ready")
    return ctl["generation"]


def receive(sqs, kind="answer"):
    return sqs.receive_message(
        QueueUrl=state.setting(kind, "QUEUE_URL"),
        MaxNumberOfMessages=1,
        VisibilityTimeout=120,
    )["Messages"][0]


def event(path, method="GET", *, admin=False, authenticated=True, body=None):
    claims = {
        "sub": "user",
        "iss": "https://issuer",
        "client_id": "client",
        "token_use": "access",
    }
    if admin:
        claims["cognito:groups"] = "[repoguide-admins]"
    return {
        "rawPath": path,
        "requestContext": {
            "http": {"method": method},
            "authorizer": {"jwt": {"claims": claims if authenticated else {}}},
        },
        "body": json.dumps(body or {}),
    }


def test_health_cannot_import_aws_models_framework_or_database():
    program = """
import sys
class Block:
 def find_spec(self, fullname, *args):
  if fullname.split('.')[0] in {'boto3','torch','sqlalchemy','psycopg','fastapi','sentence_transformers','langgraph','tree_sitter','mlflow'}: raise AssertionError(fullname)
sys.meta_path.insert(0,Block())
from repoguide.cloud_lambda import handler
assert handler({'rawPath':'/health'},None)['statusCode']==200
"""
    subprocess.run(
        [sys.executable, "-c", program],
        check=True,
        env={**os.environ, "PYTHONPATH": "src"},
    )


def test_no_job_can_start_stopped_service(cloud):
    with pytest.raises(state.Conflict, match="offline"):
        state.submit("answer", "user", {"question": "why"}, "one")
    assert cloud[2].update_service.call_count == 0
    assert scaler.reconcile("answer")["action"] == "stop"
    assert cloud[2].update_service.call_count == 0


def test_admin_start_is_explicit_independent_and_idempotent(cloud):
    first = state.start_service("answer", "admin")
    second = state.start_service("answer", "admin")
    assert first["generation"] == second["generation"]
    assert state.control("index").get("desired_state") == "off"
    assert cloud[2].update_service.call_count == 1
    state.start_service("index", "admin")
    assert cloud[2].update_service.call_count == 2


def test_unauthorized_and_forged_headers_never_start(cloud):
    assert (
        api.handler(event("/api/compute/answer/start", "POST"), None)["statusCode"]
        == 403
    )
    forged = event("/api/compute/index/start", "POST", authenticated=False)
    forged["headers"] = {"Authorization": "Bearer forged", "x-admin": "true"}
    assert api.handler(forged, None)["statusCode"] == 401
    assert cloud[2].update_service.call_count == 0


def test_transactional_acceptance_idempotency_and_tenant_ownership(cloud):
    ready()
    job = state.submit("answer", "alice", {"question": "why"}, "key")
    assert (
        state.submit("answer", "alice", {"question": "why"}, "key")["id"] == job["id"]
    )
    assert state.public_job(job["id"], "bob") is None
    assert state.control("answer")["pending"] == 1
    message = receive(cloud[1])
    assert json.loads(message["Body"]) == {"job_id": job["id"]}
    with pytest.raises(state.Conflict):
        state.submit("answer", "alice", {"question": "different"}, "key")


def test_outbox_survives_failed_send(cloud, monkeypatch):
    ready()
    original = cloud[1].send_message
    monkeypatch.setattr(cloud[1], "send_message", MagicMock(side_effect=TimeoutError))
    job = state.submit("answer", "alice", {"question": "why"}, "outbox")
    assert state.get("job#" + job["id"])["dispatch_key"] == "pending"
    monkeypatch.setattr(cloud[1], "send_message", original)
    scaler.dispatch_outbox()
    assert state.get("job#" + job["id"])["dispatch_key"] == "active#answer"
    assert json.loads(receive(cloud[1])["Body"])["job_id"] == job["id"]


def test_stop_fences_new_jobs_and_idle_scale_down_races(cloud):
    ready()
    lock = state.acquire("answer")
    with pytest.raises(Exception):
        state.submit("answer", "alice", {"question": "racing"}, "race")
    assert state.control("answer")["pending"] == 0
    state.release("answer", lock)
    state.stop_service("answer", "admin")
    with pytest.raises(state.Conflict):
        state.submit("answer", "alice", {"question": "racing"}, "race")
    scaler.reconcile("answer")
    assert state.control("answer")["desired_state"] == "off"
    assert cloud[2].update_service.call_args.kwargs["desiredCount"] == 0


def test_failed_then_healthy_job_same_process_and_models(cloud):
    generation = ready()
    failed = state.submit("answer", "alice", {"question": "bad"}, "bad")
    healthy = state.submit("answer", "alice", {"question": "good"}, "good")
    worker.handle(
        receive(cloud[1]),
        "answer",
        generation,
        "process-1",
        lambda *_: (_ for _ in ()).throw(ValueError("private diagnostic")),
    )
    calls = []

    def process(job, emit, guard):
        calls.append(job["id"])
        guard()
        emit("generation", 70, "Generating")
        return {"answer": "validated"}

    worker.handle(receive(cloud[1]), "answer", generation, "process-1", process)
    assert state.public_job(failed["id"])["status"] == "failed"
    assert state.public_job(healthy["id"])["status"] == "complete"
    assert calls == [healthy["id"]]
    assert state.control("answer")["pending"] == 0
    assert state.control("answer")["worker_id"] == "process-1"
    dlq = cloud[1].receive_message(QueueUrl=state.setting("answer", "DLQ_URL"))[
        "Messages"
    ][0]
    assert "private diagnostic" not in dlq["Body"]


def test_malformed_message_does_not_kill_consumer(cloud):
    generation = ready()
    cloud[1].send_message(
        QueueUrl=state.setting("answer", "QUEUE_URL"), MessageBody="not JSON"
    )
    worker.handle(receive(cloud[1]), "answer", generation, "process-1")
    healthy = state.submit("answer", "alice", {"question": "good"}, "good")
    worker.handle(
        receive(cloud[1]),
        "answer",
        generation,
        "process-1",
        lambda *_: {"answer": "ok"},
    )
    assert state.public_job(healthy["id"])["status"] == "complete"


def test_retries_finite_and_terminal_delivery_is_not_reexecuted(cloud):
    generation = ready()
    accepted = state.submit("answer", "alice", {"question": "bad"}, "bad")
    message = receive(cloud[1])
    processor = MagicMock(side_effect=TimeoutError)
    for _ in range(3):
        worker.handle(message, "answer", generation, "process-1", processor)
    assert state.public_job(accepted["id"])["status"] == "failed"
    worker.handle(message, "answer", generation, "process-1", processor)
    assert processor.call_count == 3
    assert state.control("answer")["pending"] == 0


def test_heartbeat_and_browser_status_never_extend_idle_timer(cloud):
    generation = ready()
    state.update("control#answer", "SET idle_since=:since", {":since": 100})
    state.worker_state("answer", generation, "process-1", "ready")
    state.status("answer")
    assert state.control("answer")["idle_since"] == 100


@pytest.mark.parametrize(
    "elapsed,expected", [(0, "wait"), (3599, "wait"), (3600, "stop"), (9000, "stop")]
)
def test_sixty_continuous_minutes_not_absolute_lifetime(elapsed, expected):
    now = 10000 + elapsed
    ctl = {
        "desired_state": "on",
        "observed_state": "ready",
        "pending": 0,
        "idle_since": 10000,
        "last_heartbeat": now,
        "start_requested_at": 1,
    }
    assert (
        scaler.idle_action(ctl, {"queued": 0, "inflight": 0, "delayed": 0}, now)
        == expected
    )
    ctl["pending"] = 1
    assert scaler.idle_action(ctl, {"queued": 0}, now) == "busy"


def test_readiness_queue_retry_and_drain_protect_work():
    now = int(time.time())
    ctl = {
        "desired_state": "on",
        "observed_state": "loading",
        "pending": 0,
        "start_requested_at": now,
    }
    assert scaler.idle_action(ctl, {}, now) == "wait"
    ctl.update(observed_state="ready", last_heartbeat=now)
    assert scaler.idle_action(ctl, {}, now) == "begin_idle"
    assert scaler.idle_action(ctl, {"delayed": 1}, now) == "busy"
    ctl.update(desired_state="draining", running_job="x", stop_requested_at=now)
    assert scaler.idle_action(ctl, {}, now) == "wait"
    assert scaler.idle_action(ctl, {}, now + 900) == "stop"


def test_stale_generation_cannot_publish_or_claim(cloud):
    generation = ready()
    job = state.submit("answer", "alice", {"question": "good"}, "good")
    raw = state.get("job#" + job["id"])
    lease = state.claim(raw, "answer", generation, "process-1")
    state.update("control#answer", "SET generation=:g", {":g": "new-generation"})
    with pytest.raises(Exception):
        state.finish(raw, lease, generation, "complete", result={"answer": "late"})
    assert state.public_job(job["id"])["status"] == "running"
    assert state.control("answer")["pending"] == 1


def test_durable_terminal_commit_is_atomic(cloud):
    generation = ready()
    job = state.submit("answer", "alice", {"question": "good"}, "good")
    raw = state.get("job#" + job["id"])
    lease = state.claim(raw, "answer", generation, "process-1")
    state.finish(raw, lease, generation, "complete", result={"answer": "ok"})
    assert state.public_job(job["id"])["status"] == "complete"
    assert state.control("answer")["pending"] == 0


def test_expired_crashed_lease_recovers_durably(cloud):
    generation = ready()
    accepted = state.submit("answer", "alice", {"question": "recover"}, "recover")
    job = state.get("job#" + accepted["id"])
    state.claim(job, "answer", generation, "process-1")
    state.update(job["pk"], "SET lease_until=:past", {":past": int(time.time()) - 400})
    scaler.reconcile("answer")
    recovered = state.get(job["pk"])
    assert recovered["status"] == "retrying"
    assert recovered["dispatch_key"] == "pending"
    assert "running_job" not in state.control("answer")
    assert state.control("answer")["pending"] == 1


def test_daily_budget_denies_new_work_without_starting_compute(cloud):
    now = int(time.time())
    cloud[0].put_item(
        TableName=state.table(),
        Item=state.encode(
            {"pk": f"limit#alice#answer#day#{now // 86400}", "requests": 30}
        ),
    )
    with pytest.raises(api.ApiError) as error:
        api.budget("alice")
    assert error.value.status == 429
    assert cloud[2].update_service.call_count == 0


def test_failed_worker_remains_visible_until_explicit_admin_restart(cloud):
    ready()
    state.update(
        "control#answer",
        "SET desired_state=:off, observed_state=:failed",
        {":off": "off", ":failed": "failed"},
    )
    scaler.reconcile("answer")
    assert state.control("answer")["observed_state"] == "failed"


def test_native_sqs_redrive_closes_orphaned_job_and_does_not_keep_worker_alive(cloud):
    ready()
    accepted = state.submit(
        "answer", "alice", {"question": "delivery budget"}, "native-dlq"
    )
    source = receive(cloud[1])
    cloud[1].delete_message(
        QueueUrl=state.setting("answer", "QUEUE_URL"),
        ReceiptHandle=source["ReceiptHandle"],
    )
    cloud[1].send_message(
        QueueUrl=state.setting("answer", "DLQ_URL"),
        MessageBody=json.dumps({"job_id": accepted["id"]}),
    )
    scaler.reconcile("answer")
    terminal = state.public_job(accepted["id"])
    assert terminal["status"] == "failed" and terminal["error_code"] == "DLQExhausted"
    assert state.control("answer")["pending"] == 0
    assert state.control("answer").get("idle_since")


def test_preflight_succeeds_without_identity_or_compute():
    from repoguide.cloud_api import handler

    result = handler(
        {
            "rawPath": "/api/compute/answer/start",
            "requestContext": {"http": {"method": "OPTIONS"}},
        },
        None,
    )
    assert result["statusCode"] == 204
    assert result["body"] == ""


def test_expired_published_queue_releases_quota_without_starting_worker(cloud):
    ready()
    job = state.submit("answer", "alice", {"question": "expired"}, "expired")
    state.update(
        "job#" + job["id"], "SET dispatch_at=:old", {":old": int(time.time()) - 86401}
    )
    state.stop_service("answer", "admin")
    starts = cloud[2].update_service.call_count
    scaler.reconcile("answer")
    assert state.public_job(job["id"], "alice")["status"] == "cancelled"
    assert state.get("useractive#answer#alice")["pending"] == 0
    assert state.control("answer")["pending"] == 0
    assert all(
        call.kwargs["desiredCount"] == 0
        for call in cloud[2].update_service.call_args_list[starts:]
    )
