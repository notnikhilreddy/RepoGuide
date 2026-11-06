"""Independent warm Answer/Index workers with a failure boundary per message."""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
import uuid

from repoguide import cloud_state as state

log = logging.getLogger(__name__)
stop_event = threading.Event()


def stop(*_):
    stop_event.set()


def timeout(*_):
    raise TimeoutError("Job execution deadline exceeded")


def warmup(kind):
    from sqlalchemy import text

    from repoguide.db import SessionLocal
    from repoguide.embeddings import get_embedding_service

    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    embedder = get_embedding_service()
    vector = embedder.encode_query("repository readiness")
    if len(vector) != 384:
        raise ValueError("Incompatible embedding dimensions")
    if kind == "answer":
        from repoguide.reranker import get_reranker
        from repoguide.workflow import graph

        get_reranker().predict([("repository", "repository code")])
        graph()


def execute(job, emit, guard):
    payload = json.loads(job["payload"])
    if job["kind"] == "answer":
        from repoguide.pipeline import answer

        payload = {
            k: v for k, v in payload.items() if k not in {"conversation_id", "turn_id"}
        }
        emit("retrieval", 5, "Retrieving repository evidence")
        result = answer(**payload, tenant=job["owner_sub"], progress=emit)
        guard()
        return result.model_dump()
    from sqlalchemy import text

    from repoguide import cloud_product as product
    from repoguide.db import SessionLocal
    from repoguide.indexer import index_repository

    with SessionLocal() as db:
        capacity = (
            db.execute(
                text(
                    "SELECT pg_database_size(current_database()) AS bytes,(SELECT count(*) FROM chunks) AS chunks"
                )
            )
            .mappings()
            .one()
        )
        if capacity["bytes"] > 350 * 1024 * 1024 or capacity["chunks"] > 50000:
            raise ValueError(
                "The demo's shared index storage allowance has been reached"
            )
        repo = index_repository(
            payload["url"],
            db,
            force=payload.get("force", False),
            progress=emit,
            commit_sha=payload.get("commit_sha"),
            commit_guard=guard,
            owner_sub=job["owner_sub"],
            base_repo_id=payload.get("base_repo_id"),
            branch=payload.get("branch"),
        )
        guard()
        previous = (
            product.require_repository(
                payload["base_repo_id"], job["owner_sub"], write=True
            )
            if payload.get("base_repo_id")
            else None
        )
        product.grant_repository(
            repo.id,
            job["owner_sub"],
            shared=bool(previous and previous.get("visibility") == "shared"),
            branch=payload.get("branch"),
            private_github=bool(payload.get("private")),
            freshness_status="up_to_date"
            if payload.get("resolved_from_branch")
            else "unknown",
            remote_sha=repo.commit_sha if payload.get("resolved_from_branch") else "",
            checked_at=payload.get("remote_checked_at", 0)
            if payload.get("resolved_from_branch")
            else 0,
            branch_explicit=payload.get("branch_explicit", False),
            default_branch_checked_at=int(time.time()),
            remote_message=payload.get("commit_message", ""),
        )
        if previous and previous["repo_id"] != repo.id:
            state.update(
                previous["pk"],
                "SET superseded_by=:new REMOVE catalog_pk, catalog_sk",
                {":new": repo.id},
            )
        product.record_usage(
            job["owner_sub"],
            {
                k: (repo.index_metadata or {}).get(k, 0)
                for k in ("indexed_files", "embedded_chunks", "reused_chunks")
            },
        )
        return {
            "repo_id": repo.id,
            "url": repo.url,
            "commit_sha": repo.commit_sha,
            "index_metadata": repo.index_metadata,
        }


def handle(message, kind, generation, worker_id, processor=execute):
    sqs = state.clients()[1]
    receipt = message["ReceiptHandle"]
    queue = state.setting(kind, "QUEUE_URL")
    job, lease = None, None
    output = None
    done = threading.Event()
    watcher = None

    def ack():
        sqs.delete_message(QueueUrl=queue, ReceiptHandle=receipt)

    def deadletter(reason):
        # Diagnostic is deliberately ID/type-only, never the untrusted raw body.
        sqs.send_message(
            QueueUrl=state.setting(kind, "DLQ_URL"),
            MessageBody=json.dumps(
                {"job_id": job["id"] if job else None, "error_type": reason}
            ),
        )

    try:
        data = json.loads(message["Body"])
        job_id = str(uuid.UUID(data["job_id"]))
        job = state.get("job#" + job_id)
        if not job or job.get("kind") != kind:
            deadletter("UnknownJob")
            ack()
            return
        if job["status"] in state.TERMINAL:
            ack()
            return
        try:
            lease = state.claim(job, kind, generation, worker_id)
        except Exception:
            # Duplicate delivery or Start/Stop race: do not steal an active lease.
            sqs.change_message_visibility(
                QueueUrl=queue, ReceiptHandle=receipt, VisibilityTimeout=120
            )
            return
        job = state.get(job["pk"])

        def guard():
            ctl, current = state.control(kind), state.get(job["pk"])
            if (
                ctl.get("generation") != generation
                or ctl.get("worker_id") != worker_id
                or ctl.get("desired_state") not in {"on", "draining"}
                or current.get("lease_token") != lease
                or int(current.get("lease_until", 0)) <= int(time.time())
            ):
                raise RuntimeError("Job lease lost")
            if current.get("cancel_requested"):
                raise state.JobCancelled("Answer stopped")

        def heartbeat():
            while not done.wait(30):
                try:
                    guard()
                    sqs.change_message_visibility(
                        QueueUrl=queue, ReceiptHandle=receipt, VisibilityTimeout=120
                    )
                    state.update(
                        job["pk"],
                        "SET lease_until=:until",
                        {":until": int(time.time()) + 180, ":lease": lease},
                        "lease_token=:lease",
                    )
                except state.JobCancelled:
                    return
                except Exception as exc:
                    log.error(
                        json.dumps(
                            {
                                "event": "lease_renewal_failed",
                                "job_id": job["id"],
                                "error_type": type(exc).__name__,
                            }
                        )
                    )

        watcher = threading.Thread(target=heartbeat, daemon=True)
        watcher.start()

        def emit(stage, percent, detail):
            guard()
            state.progress(
                job["id"], lease, stage, percent if kind == "index" else 0, detail
            )

        if threading.current_thread() is threading.main_thread():
            signal.alarm(900 if kind == "index" else 600)
        output = processor(job, emit, guard)
        guard()
        state.finish(job, lease, generation, "complete", result=output)
        # The job is already durable. Chat recovery retries this merge on read
        # if an S3 write is interrupted; never repeat paid generation for it.
        try:
            from repoguide import cloud_product as product

            data = json.loads(job["payload"])
            if data.get("conversation_id"):
                product.complete_turn(
                    job["owner_sub"],
                    data["conversation_id"],
                    data["turn_id"],
                    state.public_job(job["id"], job["owner_sub"]),
                )
            if kind == "answer":
                usage = output.get("usage", {})
                product.record_usage(
                    job["owner_sub"],
                    {
                        **usage,
                        "requests": 1,
                        "answers": 1,
                        "abstentions": int(
                            output.get("status") == "insufficient_evidence"
                        ),
                        "valid_citations": len(output.get("verified_labels", [])),
                    },
                )
        except Exception as delivery_error:
            log.warning(
                json.dumps(
                    {
                        "event": "product_metadata_retry_on_read",
                        "error_type": type(delivery_error).__name__,
                    }
                )
            )
        ack()
        log.info(
            json.dumps(
                {
                    "event": "job_complete",
                    "kind": kind,
                    "job_id": job["id"],
                    "worker_id": worker_id,
                    "attempt": int(job["attempt"]),
                }
            )
        )
    except Exception as exc:
        error = type(exc).__name__
        try:
            from repoguide import cloud_product as product

            if (
                job
                and kind == "answer"
                and state.get(job["pk"]).get("status") not in state.TERMINAL
            ):
                usage = getattr(exc, "repoguide_usage", None) or (output or {}).get(
                    "usage", {}
                )
                product.record_usage(
                    job["owner_sub"],
                    {k: v for k, v in usage.items() if k != "latency_ms"}
                    | {
                        "requests": 1,
                        "cancelled_requests": int(isinstance(exc, state.JobCancelled)),
                        "failed_requests": int(not isinstance(exc, state.JobCancelled)),
                    },
                )
        except Exception:
            pass
        log.error(
            json.dumps(
                {
                    "event": "job_error",
                    "kind": kind,
                    "job_id": job["id"] if job else None,
                    "error_type": error,
                }
            )
        )
        try:
            if lease and job:
                current = state.get(job["pk"])
                if current.get("status") in state.TERMINAL:
                    return  # Durable success precedes an ACK failure; redelivery ACKs.
                permanent = isinstance(exc, (ValueError, KeyError, TypeError))
                if isinstance(exc, state.JobCancelled):
                    state.finish(
                        job, lease, generation, "cancelled", error="Stopped by owner"
                    )
                    ack()
                elif permanent or int(job["attempt"]) >= 3:
                    deadletter(error)
                    state.finish(job, lease, generation, "failed", error=error)
                    ack()
                else:
                    state.retry(job, lease, generation, error)
                    sqs.change_message_visibility(
                        QueueUrl=queue,
                        ReceiptHandle=receipt,
                        VisibilityTimeout=min(30 * 2 ** int(job["attempt"]), 240),
                    )
            else:
                deadletter(error)
                ack()
        except Exception as persist_error:
            log.error(
                json.dumps(
                    {
                        "event": "failure_persistence_retry",
                        "error_type": type(persist_error).__name__,
                    }
                )
            )
    finally:
        if threading.current_thread() is threading.main_thread():
            signal.alarm(0)
        done.set()
        if watcher:
            watcher.join(timeout=2)


def run():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGALRM, timeout)
    kind = os.environ["REPOGUIDE_WORKER_KIND"]
    ctl = state.control(kind)
    if ctl.get("desired_state") != "on":
        return
    generation, worker_id = ctl["generation"], str(uuid.uuid4())
    from repoguide.cloud_bootstrap import hydrate_runtime_env

    hydrate_runtime_env()
    # Evaluated model/prompt configuration is baked into the image, not mutable SSM.
    from pathlib import Path

    manifest = Path("/opt/repoguide/release-config.json")
    if manifest.exists():
        os.environ.update(json.loads(manifest.read_text())["runtime"])
    state.worker_state(kind, generation, worker_id, "loading")

    def heartbeat():
        while not stop_event.wait(30):
            try:
                ctl = state.control(kind)
                if (
                    ctl.get("desired_state") == "off"
                    or ctl.get("generation") != generation
                ):
                    stop_event.set()
                    return
                observed = (
                    "draining"
                    if ctl.get("desired_state") == "draining"
                    else ("ready" if ready.is_set() else "loading")
                )
                state.worker_state(kind, generation, worker_id, observed)
            except Exception as exc:
                log.error(
                    json.dumps(
                        {
                            "event": "worker_heartbeat_failed",
                            "error_type": type(exc).__name__,
                        }
                    )
                )

    ready = threading.Event()
    watcher = threading.Thread(target=heartbeat, daemon=True)
    watcher.start()
    try:
        started = time.monotonic()
        try:
            warmup(kind)
        except Exception as exc:
            state.update(
                "control#" + kind,
                "SET startup_failures=if_not_exists(startup_failures,:zero)+:one, last_error=:error",
                {":zero": 0, ":one": 1, ":error": type(exc).__name__, ":g": generation},
                "generation=:g",
            )
            raise
        state.worker_state(
            kind,
            generation,
            worker_id,
            "ready",
            startup_ms=int((time.monotonic() - started) * 1000),
            release_id=os.getenv("REPOGUIDE_RELEASE", "local"),
            model_version=os.getenv(
                os.getenv("LLM_PROVIDER", "gemini").upper() + "_MODEL", "unknown"
            )
            if kind == "answer"
            else "all-MiniLM-L6-v2 / 384 dimensions",
        )
        ready.set()
        log.info(
            json.dumps(
                {
                    "event": "worker_ready",
                    "kind": kind,
                    "worker_id": worker_id,
                    "generation": generation,
                }
            )
        )
        while not stop_event.is_set():
            ctl = state.control(kind)
            if ctl.get("generation") != generation or ctl.get("desired_state") != "on":
                stop_event.wait(2)
                continue
            try:
                messages = (
                    state.clients()[1]
                    .receive_message(
                        QueueUrl=state.setting(kind, "QUEUE_URL"),
                        MaxNumberOfMessages=1,
                        WaitTimeSeconds=10,
                        VisibilityTimeout=120,
                        MessageSystemAttributeNames=["ApproximateReceiveCount"],
                    )
                    .get("Messages", [])
                )
                for message in messages:
                    handle(message, kind, generation, worker_id)
            except Exception as exc:
                log.error(
                    json.dumps(
                        {"event": "poll_failed", "error_type": type(exc).__name__}
                    )
                )
                stop_event.wait(3)
    finally:
        stop_event.set()
        watcher.join(timeout=2)


if __name__ == "__main__":
    run()
