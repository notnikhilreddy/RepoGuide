"""SQS long-polling Fargate worker. Acknowledge messages ONLY after durable success.
Visibility is renewed while a job is running; duplicates are harmless on success.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import uuid

from repoguide.cloud_bootstrap import hydrate_runtime_env

hydrate_runtime_env()

from repoguide.cloud_jobs import clients, get_job, update_job  # noqa: E402
from repoguide.db import SessionLocal  # noqa: E402
from repoguide.indexer import index_repository  # noqa: E402

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger("repoguide.worker")
stop_event = threading.Event()


def stop(*_):
    stop_event.set()


def handle(message: dict) -> None:
    _, sqs, _ = clients()
    job = json.loads(message["Body"])
    job_id = str(uuid.UUID(job["job_id"]))
    existing = get_job(job_id)
    if existing is None:
        raise ValueError("Job status row is missing")
    if existing["status"] == "complete":
        sqs.delete_message(
            QueueUrl=os.environ["REPOGUIDE_QUEUE_URL"],
            ReceiptHandle=message["ReceiptHandle"],
        )
        return
    receipt = message["ReceiptHandle"]
    heartbeat_stop = threading.Event()

    def heartbeat():
        while not heartbeat_stop.wait(180):
            try:
                sqs.change_message_visibility(
                    QueueUrl=os.environ["REPOGUIDE_QUEUE_URL"],
                    ReceiptHandle=receipt,
                    VisibilityTimeout=900,
                )
            except Exception:
                log.exception("Visibility extension failed for %s", job_id)

    watcher = threading.Thread(target=heartbeat, daemon=True)
    watcher.start()
    try:
        update_job(
            job_id,
            status="running",
            stage="starting",
            percent=1,
            detail="Fargate worker started",
        )

        def emit(stage: str, percent: int, detail: str):
            update_job(
                job_id,
                status="running",
                stage=stage,
                percent=int(percent),
                detail=detail,
            )

        with SessionLocal() as session:
            repo = index_repository(
                job["url"], session, force=bool(job.get("force")), progress=emit
            )
            output = {
                "repo_id": repo.id,
                "url": repo.url,
                "commit_sha": repo.commit_sha,
            }
        # Store lightweight durable job artifact; underlying code snapshots live in Postgres.
        import boto3

        boto3.client("s3").put_object(
            Bucket=os.environ["REPOGUIDE_ARTIFACT_BUCKET"],
            Key=f"jobs/{job_id}.json",
            Body=json.dumps(output).encode(),
            ContentType="application/json",
        )
        update_job(
            job_id,
            status="complete",
            stage="complete",
            percent=100,
            detail="Indexed",
            result=output,
        )
        sqs.delete_message(
            QueueUrl=os.environ["REPOGUIDE_QUEUE_URL"], ReceiptHandle=receipt
        )
        log.info("Completed job %s", job_id)
    except Exception:
        log.exception("Worker job failed %s; message will retry", job_id)
        attempts = int(message.get("Attributes", {}).get("ApproximateReceiveCount", 1))
        update_job(
            job_id,
            status="failed" if attempts >= 3 else "retrying",
            stage="failed",
            percent=0,
            detail="Worker failed; inspect CloudWatch logs",
        )
        # Leave message in queue for retry/DLQ; do not acknowledge on failure.
    finally:
        heartbeat_stop.set()
        watcher.join(timeout=3)


def run():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    _, sqs, _ = clients()
    url = os.environ["REPOGUIDE_QUEUE_URL"]
    log.info("Worker online")
    while not stop_event.is_set():
        messages = sqs.receive_message(
            QueueUrl=url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=10,
            VisibilityTimeout=900,
            MessageSystemAttributeNames=["ApproximateReceiveCount"],
        ).get("Messages", [])
        for message in messages:
            handle(message)
    log.info("Worker shutting down")


if __name__ == "__main__":
    run()
