"""Durable content, competing tabs, owner isolation and job recovery with Moto."""

import json
import uuid
from unittest.mock import MagicMock

import boto3
import pytest
import test_cloud_architecture as contracts
from test_cloud_architecture import event, ready, receive

from repoguide import cloud_api as api
from repoguide import cloud_product as product
from repoguide import cloud_state as state
from repoguide import cloud_worker as worker

cloud = contracts.cloud


@pytest.fixture
def stored(cloud, monkeypatch):
    db = cloud[0]
    db.update_table(
        TableName=state.table(),
        AttributeDefinitions=[
            {"AttributeName": "catalog_pk", "AttributeType": "S"},
            {"AttributeName": "catalog_sk", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexUpdates=[
            {
                "Create": {
                    "IndexName": "catalog",
                    "KeySchema": [
                        {"AttributeName": "catalog_pk", "KeyType": "HASH"},
                        {"AttributeName": "catalog_sk", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            }
        ],
    )
    monkeypatch.setenv("REPOGUIDE_ARTIFACT_BUCKET", "product-test-bucket")
    s3 = boto3.client("s3")
    s3.create_bucket(
        Bucket="product-test-bucket",
        CreateBucketConfiguration={"LocationConstraint": "us-east-2"},
    )
    repo_id = str(uuid.uuid4())
    product.grant_repository(repo_id, "user", branch="main")
    monkeypatch.setattr(api, "configure", lambda: None)
    return cloud, repo_id, s3


def test_private_repositories_are_fail_closed_and_shared_is_read_only(stored):
    _, repo_id, _ = stored
    assert product.require_repository(repo_id, "user")["visibility"] == "private"
    with pytest.raises(LookupError):
        product.require_repository(repo_id, "other")
    product.grant_repository(repo_id, "user", shared=True)
    assert product.require_repository(repo_id, "other")["visibility"] == "shared"
    with pytest.raises(LookupError):
        product.require_repository(repo_id, "other", write=True)
    with pytest.raises(state.Conflict):
        product.grant_repository(repo_id, "other")
    with pytest.raises(LookupError):
        product.require_repository(str(uuid.uuid4()), "user")


def test_s3_is_authoritative_and_history_is_owned_across_sessions(stored):
    _, repo_id, s3 = stored
    document = product.create_conversation("user", repo_id)
    row = state.get(product.metadata_key("user", document["id"]))
    assert "messages" not in row and "answer" not in row
    persisted = json.loads(
        s3.get_object(
            Bucket=product.bucket(),
            Key=product.conversation_key("user", document["id"]),
        )["Body"].read()
    )
    assert persisted == product.get_conversation("user", document["id"])
    with pytest.raises(LookupError):
        product.get_conversation("other", document["id"])
    product.rename_conversation("user", document["id"], "Trace request flow")
    assert (
        product.list_conversations("user", {"q": "request"})[0]["title"]
        == "Trace request flow"
    )
    assert product.list_conversations("other", {}) == []


def test_competing_s3_writes_cannot_lose_a_turn(stored):
    _, repo_id, _ = stored
    document = product.create_conversation("user", repo_id)
    stale, etag = product._read("user", document["id"])
    product.rename_conversation("user", document["id"], "Newer title")
    stale["title"] = "Stale tab"
    with pytest.raises(state.Conflict):
        product._write("user", stale, etag)
    assert product.get_conversation("user", document["id"])["title"] == "Newer title"


def test_large_answers_spill_to_durable_s3_and_delete_removes_assets(stored):
    _, repo_id, s3 = stored
    document = product.create_conversation("user", repo_id)

    def add_large_answers(current):
        current["messages"] = [
            {
                "id": str(uuid.uuid4()),
                "role": "assistant",
                "status": "complete",
                "answer": {
                    "answer": "evidence " + ("é" * 50000),
                    "sources": [],
                    "docs_sources": [],
                },
                "created_at": 1,
            }
            for _ in range(9)
        ]

    product.mutate("user", document["id"], add_large_answers)
    raw, _ = product._read("user", document["id"])
    assert any(m.get("answer_ref") and not m.get("answer") for m in raw["messages"])
    restored = product.get_conversation("user", document["id"])
    assert len(restored["messages"]) == 9 and all(
        m["answer"]["answer"].endswith("é" * 50000) for m in restored["messages"]
    )
    product.delete_conversation("user", document["id"])
    prefix = f"conversations/{product.namespace('user')}/{document['id']}/"
    assert not s3.list_objects_v2(Bucket=product.bucket(), Prefix=prefix).get(
        "Contents"
    )


def test_deleted_conversation_fences_transactional_job_acceptance(stored):
    _, repo_id, _ = stored
    ready()
    document = product.create_conversation("user", repo_id)
    product.delete_conversation("user", document["id"])
    with pytest.raises(Exception):
        state.submit(
            "answer",
            "user",
            {
                "repo_id": repo_id,
                "conversation_id": document["id"],
                "question": "must not execute",
            },
            "deleted",
        )
    assert state.control("answer")["pending"] == 0


def test_delete_cancels_an_accepted_job_even_after_metadata_rename(stored):
    _, repo_id, _ = stored
    ready()
    document = product.create_conversation("user", repo_id)
    result = product.submit_turn(
        "user",
        document["id"],
        {"message_id": str(uuid.uuid4()), "question": "Stop on deletion"},
        api.validate_answer,
        lambda *_: None,
    )
    product.rename_conversation("user", document["id"], "New title")
    assert (
        state.get(product.metadata_key("user", document["id"]))["active_job_id"]
        == result["job"]["id"]
    )
    product.delete_conversation("user", document["id"])
    assert state.get("job#" + result["job"]["id"])["status"] == "cancelled"
    assert state.public_job(result["job"]["id"], "user") is None
    assert state.control("answer")["pending"] == 0


def test_offline_submission_is_saved_without_starting_or_queuing_compute(stored):
    cloud, repo_id, _ = stored
    document = product.create_conversation("user", repo_id)
    with pytest.raises(state.Conflict, match="offline"):
        product.submit_turn(
            "user",
            document["id"],
            {"message_id": str(uuid.uuid4()), "question": "Remember this question"},
            api.validate_answer,
            lambda *_: None,
        )
    saved = product.get_conversation("user", document["id"])
    assert saved["messages"][0]["content"] == "Remember this question"
    assert (
        saved["messages"][-1]["status"] == "failed"
        and "offline" in saved["messages"][-1]["error"]
    )
    assert cloud[2].update_service.call_count == 0


def test_delete_tombstone_prevents_worker_resurrection(stored):
    _, repo_id, s3 = stored
    document = product.create_conversation("user", repo_id)
    stale, etag = product._read("user", document["id"])
    product.delete_conversation("user", document["id"])
    with pytest.raises(LookupError):
        product._write("user", stale, etag)
    with pytest.raises(LookupError):
        product.get_conversation("user", document["id"])
    assert product.list_conversations("user", {}) == []


def test_saved_answer_keeps_citations_and_reconciles_after_interrupted_delivery(stored):
    cloud, repo_id, _ = stored
    generation = ready()
    document = product.create_conversation("user", repo_id)
    turn = str(uuid.uuid4())
    result = product.submit_turn(
        "user",
        document["id"],
        {"message_id": turn, "question": "How does this work?"},
        api.validate_answer,
        lambda *_: None,
    )
    receive(cloud[1])
    raw = state.get("job#" + result["job"]["id"])
    lease = state.claim(raw, "answer", generation, "process-1")
    answer = {
        "answer": "Supported [S1]",
        "sources": [
            {
                "label": "S1",
                "repo_id": repo_id,
                "commit_sha": "a" * 40,
                "file_path": "main.py",
                "start_line": 1,
                "end_line": 4,
                "url": "https://github.com/example/code/blob/"
                + "a" * 40
                + "/main.py#L1-L4",
            }
        ],
        "docs_sources": [],
        "trace_id": "trace-test",
    }
    state.finish(state.get(raw["pk"]), lease, generation, "complete", result=answer)
    # No worker S3 callback happened. A new browser read must merge the durable job.
    restored = product.get_conversation("user", document["id"])
    assert "active_turn" not in restored
    assert restored["messages"][-1]["answer"] == answer
    assert state.get("useractive#answer#user")["pending"] == 0
    assert len(product.get_conversation("user", document["id"])["messages"]) == 2
    with pytest.raises(LookupError):
        product.submit_turn(
            "other",
            document["id"],
            {"message_id": str(uuid.uuid4()), "question": "steal"},
            api.validate_answer,
            lambda *_: None,
        )


def test_failed_submission_saves_question_without_sticking_conversation(
    stored, monkeypatch
):
    _, repo_id, _ = stored
    ready()
    document = product.create_conversation("user", repo_id)
    monkeypatch.setattr(state, "submit", MagicMock(side_effect=state.Conflict("busy")))
    with pytest.raises(state.Conflict):
        product.submit_turn(
            "user",
            document["id"],
            {"message_id": str(uuid.uuid4()), "question": "Saved question"},
            api.validate_answer,
            lambda *_: None,
        )
    restored = product.get_conversation("user", document["id"])
    assert restored["messages"][0]["content"] == "Saved question"
    assert restored["messages"][-1]["status"] == "failed"
    assert not restored.get("active_turn")


def test_delivery_outbox_keeps_result_until_s3_is_durable(stored, monkeypatch):
    cloud, repo_id, _ = stored
    generation = ready()
    document = product.create_conversation("user", repo_id)
    turn = str(uuid.uuid4())
    result = product.submit_turn(
        "user",
        document["id"],
        {"message_id": turn, "question": "Keep the completed answer"},
        api.validate_answer,
        lambda *_: None,
    )
    receive(cloud[1])
    raw = state.get("job#" + result["job"]["id"])
    lease = state.claim(raw, "answer", generation, "process-1")
    answer = {
        "answer": "A durable answer [S1]",
        "sources": [
            {"label": "S1", "file_path": "main.py", "start_line": 1, "end_line": 3}
        ],
        "docs_sources": [],
    }
    state.finish(state.get(raw["pk"]), lease, generation, "complete", result=answer)
    assert "expires_at" not in state.get(raw["pk"])
    assert state.get("chat-delivery#" + raw["id"])
    assert state.control("answer")["pending"] == 0
    with monkeypatch.context() as patch:
        patch.setattr(
            product,
            "_write",
            MagicMock(side_effect=RuntimeError("S3 temporarily unavailable")),
        )
        with pytest.raises(RuntimeError):
            product.retry_chat_deliveries()
    assert "expires_at" not in state.get(raw["pk"])
    row = state.get("chat-delivery#" + raw["id"])
    assert row["delivery_attempt"] == 1 and row["due_at"] > 0
    state.update(
        row["pk"],
        "SET due_at=:zero, catalog_sk=:s",
        {":zero": 0, ":s": "delivery#000000000000#" + raw["id"]},
    )
    product.retry_chat_deliveries()
    assert state.get(raw["pk"])["expires_at"] > 0
    assert not state.get("chat-delivery#" + raw["id"])
    assert (
        product.get_conversation("user", document["id"])["messages"][-1]["answer"]
        == answer
    )


def test_outstanding_quota_and_cancellation_release_capacity(stored):
    _, repo_id, _ = stored
    ready()
    first = state.submit(
        "answer", "user", {"repo_id": repo_id, "question": "first"}, "first"
    )
    state.submit("answer", "user", {"repo_id": repo_id, "question": "second"}, "second")
    with pytest.raises(Exception):
        state.submit(
            "answer", "user", {"repo_id": repo_id, "question": "third"}, "third"
        )
    with pytest.raises(LookupError):
        state.cancel_job(first["id"], "other")
    assert state.cancel_job(first["id"], "user")["status"] == "cancelled"
    assert state.get("useractive#answer#user")["pending"] == 1
    assert (
        state.submit(
            "answer", "user", {"repo_id": repo_id, "question": "third"}, "third"
        )["status"]
        == "queued"
    )


def test_running_cancel_is_owner_scoped_and_worker_continues(stored):
    cloud, repo_id, _ = stored
    generation = ready()
    job = state.submit(
        "answer", "user", {"repo_id": repo_id, "question": "stop"}, "stop"
    )

    def process(current, emit, guard):
        assert state.cancel_job(current["id"], "user")["cancel_requested"]
        guard()
        raise AssertionError("Cancelled work continued")

    worker.handle(receive(cloud[1]), "answer", generation, "process-1", process)
    assert state.public_job(job["id"], "user")["status"] == "cancelled"
    assert state.get("useractive#answer#user")["pending"] == 0
    next_job = state.submit(
        "answer", "user", {"repo_id": repo_id, "question": "healthy"}, "healthy"
    )
    worker.handle(
        receive(cloud[1]),
        "answer",
        generation,
        "process-1",
        lambda *_: {"answer": "healthy"},
    )
    assert state.public_job(next_job["id"], "user")["status"] == "complete"


def test_feedback_requires_owned_completed_message_and_usage_never_accepts_owner_query(
    stored,
):
    cloud, repo_id, _ = stored
    ready()
    job = state.submit(
        "answer", "other", {"repo_id": repo_id, "question": "other"}, "other"
    )
    response = api.handler(
        event(
            "/feedback",
            "POST",
            body={"job_id": job["id"], "rating": 1, "category": "incorrect"},
        ),
        None,
    )
    assert response["statusCode"] == 404
    product.record_usage(
        "user", {"answers": 2, "input_tokens": 100, "estimated_cost_micros": 25}
    )
    product.record_usage("other", {"answers": 9, "input_tokens": 900})
    result = api.handler(event("/api/usage"), None)
    assert result["statusCode"] == 200
    days = json.loads(result["body"])["days"]
    assert len(days) == 1 and days[0]["answers"] == 2 and days[0]["input_tokens"] == 100


def test_feedback_survives_job_expiry_and_checks_saved_message_owner(stored):
    _, repo_id, _ = stored
    document = product.create_conversation("user", repo_id)
    message_id, job_id = str(uuid.uuid4()), str(uuid.uuid4())
    product.mutate(
        "user",
        document["id"],
        lambda d: d["messages"].append(
            {
                "id": message_id,
                "role": "assistant",
                "status": "complete",
                "job_id": job_id,
                "answer": {"answer": "Saved answer", "trace_id": "trace-1"},
            }
        ),
    )
    body = {
        "job_id": job_id,
        "conversation_id": document["id"],
        "message_id": message_id,
        "rating": 5,
        "category": "helpful",
    }
    response = api.handler(event("/feedback", "POST", body=body), None)
    assert response["statusCode"] == 200
    row = state.get("feedback#" + job_id + "#" + product.namespace("user"))
    assert row["trace_id"] == "trace-1" and row["message_id"] == message_id
    foreign = event("/feedback", "POST", body=body)
    foreign["requestContext"]["authorizer"]["jwt"]["claims"]["sub"] = "other"
    response = api.handler(foreign, None)
    assert response["statusCode"] == 404
