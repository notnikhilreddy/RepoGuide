"""Run real CPU model processes and fail-then-success jobs against Moto + local DB.

SQS/DynamoDB/SSM transport is emulated; cloning, parsing, CPU models, PostgreSQL
and citation validation are real. Generation uses a provider fixture while live
evaluation is paused. No production DB is used.
"""

from __future__ import annotations

import fcntl
import json
import os
import platform
import subprocess
import sys
import time
import uuid
from pathlib import Path

import boto3
from update_runtime_settings import load_settings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from repoguide import cloud_state as state  # noqa: E402

# The fixture database is shared by the two local container roles. Serialize
# harness runs, and keep transport state unique even after an interrupted run.
lock = (ROOT / ".artifacts/local-worker-test.lock").open("a")
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit(
        "Another local worker harness is running; run these tests sequentially"
    ) from None

KIND = sys.argv[1]
ENDPOINT = "http://127.0.0.1:5500"
os.environ.update(
    AWS_DEFAULT_REGION="us-east-2",
    AWS_ACCESS_KEY_ID="testing",
    AWS_SECRET_ACCESS_KEY="testing",
    AWS_ENDPOINT_URL=ENDPOINT,
    REPOGUIDE_JOB_TABLE="local-worker-" + uuid.uuid4().hex[:10],
    REPOGUIDE_ECS_CLUSTER="local",
)
state.clients.cache_clear()
session = boto3.Session(
    region_name="us-east-2",
    aws_access_key_id="testing",
    aws_secret_access_key="testing",
)
db, sqs, ssm = (
    session.client(name, endpoint_url=ENDPOINT) for name in ["dynamodb", "sqs", "ssm"]
)
try:
    db.create_table(
        TableName=os.environ["REPOGUIDE_JOB_TABLE"],
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
    )
except db.exceptions.ResourceInUseException:
    pass
for kind in state.KINDS:
    os.environ["REPOGUIDE_" + kind.upper() + "_SERVICE"] = kind
    for suffix in ["QUEUE_URL", "DLQ_URL"]:
        os.environ["REPOGUIDE_" + kind.upper() + "_" + suffix] = sqs.create_queue(
            QueueName=os.environ["REPOGUIDE_JOB_TABLE"] + "-" + kind + suffix
        )["QueueUrl"]
generation = str(uuid.uuid4())
db.put_item(
    TableName=state.table(),
    Item=state.encode(
        {
            "pk": "control#" + KIND,
            "generation": generation,
            "desired_state": "on",
            "observed_state": "starting",
            "start_requested_at": int(time.time()),
            "pending": 0,
        }
    ),
)
values = load_settings(ROOT / ".env.deploy")
secret_keys = []  # Live LLM evaluation is paused; use only the provider fixture.
config = {k: values[k] for k in secret_keys if values.get(k)}
config["DATABASE_URL"] = (
    "postgresql+psycopg://repoguide:repoguide@host.docker.internal:55432/repoguide?sslmode=require&connect_timeout=5"
)
parameter = "/local/" + KIND
ssm.put_parameter(
    Name=parameter, Value=json.dumps(config), Type="SecureString", Overwrite=True
)
image = "repoguide-" + KIND + ":candidate"
image_id = subprocess.check_output(
    ["docker", "image", "inspect", image, "--format", "{{.Id}}"], text=True
).strip()
env = {
    **os.environ,
    "AWS_ENDPOINT_URL": "http://host.docker.internal:5500",
    "REPOGUIDE_WORKER_KIND": KIND,
    "REPOGUIDE_SSM_PARAMETER": parameter,
    "REPOGUIDE_CLOUD_MODE": "true",
    "MLFLOW_ENABLED": "false",
    "REPOGUIDE_EVALUATION": "true",
}
args = [
    "docker",
    "run",
    "-d",
    "--platform",
    "linux/amd64",
    "--cpus",
    "1",
    "--memory",
    "4g",
    "--read-only",
    "--mount",
    "type=volume,destination=/tmp",
]
if platform.system() == "Linux":
    args += ["--network", "host", "--add-host", "host.docker.internal:127.0.0.1"]
# Moto returns URLs using its request host, so rewrite only queue hostnames for
# the container. Queue identity remains the same emulated account/queue path.
for key in list(env):
    if key.startswith("REPOGUIDE_") and key.endswith(("_QUEUE_URL", "_DLQ_URL")):
        env[key] = env[key].replace("127.0.0.1", "host.docker.internal")
for key in [
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_DEFAULT_REGION",
    "AWS_ENDPOINT_URL",
    "REPOGUIDE_WORKER_KIND",
    "REPOGUIDE_SSM_PARAMETER",
    "REPOGUIDE_CLOUD_MODE",
    "REPOGUIDE_EVALUATION",
    "MLFLOW_ENABLED",
    "REPOGUIDE_JOB_TABLE",
] + [
    k
    for k in env
    if k.startswith("REPOGUIDE_") and k.endswith(("_SERVICE", "_QUEUE_URL", "_DLQ_URL"))
]:
    args += ["--env", key]
if KIND == "answer":
    args += [
        "-v",
        str(ROOT / "scripts") + ":/scripts:ro",
        image,
        "python",
        "/scripts/fixture_answer_worker.py",
    ]
else:
    args += [image]
container = subprocess.check_output(args, env=env, text=True).strip()
start = time.monotonic()
report = {
    "kind": KIND,
    "image_id": image_id,
    "transport": "Moto SQS/DynamoDB/SSM",
    "database": "disposable local PostgreSQL",
    "models": "real offline CPU weights",
    "generation": "reviewed provider fixture (not live generation)"
    if KIND == "answer"
    else None,
}
try:
    while state.control(KIND).get("observed_state") != "ready":
        running = subprocess.check_output(
            ["docker", "inspect", container, "--format", "{{.State.Running}}"],
            text=True,
        ).strip()
        if running != "true":
            raise RuntimeError("Worker exited before readiness")
        if time.monotonic() - start > 240:
            raise TimeoutError("Worker readiness timeout")
        time.sleep(2)
    report["ready_seconds"] = time.monotonic() - start
    worker_id = state.control(KIND)["worker_id"]
    bad_payload = (
        {"url": "file:///etc/passwd"}
        if KIND == "index"
        else {"unexpected_argument": True}
    )
    bad = state.submit(KIND, "local-user", bad_payload, str(uuid.uuid4()))
    payload = (
        {
            "url": "https://github.com/notnikhilreddy/RepoGuide",
            "commit_sha": "4aa70f5cbf345ab83ab7cc14257d79da6a8ee416",
            "force": KIND == "index",
        }
        if KIND == "index"
        else {
            "repo_id": json.loads((ROOT / ".artifacts/fixture.json").read_text())[
                "repo_id"
            ],
            "question": "How does index_repository commit database changes and roll back failures?",
            "docs_policy": "never",
            "retrieval_mode": "hybrid",
            "answer_depth": "standard",
            "top_k": 8,
        }
    )
    healthy = state.submit(KIND, "local-user", payload, str(uuid.uuid4()))
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        failed, complete = state.public_job(bad["id"]), state.public_job(healthy["id"])
        if failed["status"] == "failed" and complete["status"] in state.TERMINAL:
            break
        time.sleep(2)
    if complete["status"] == "complete":
        repeat_payload = {**payload, **({"force": False} if KIND == "index" else {})}
        repeat = state.submit(KIND, "local-user", repeat_payload, str(uuid.uuid4()))
        repeat_start = time.monotonic()
        while time.monotonic() - repeat_start < 120:
            repeated = state.public_job(repeat["id"])
            if repeated["status"] in state.TERMINAL:
                break
            time.sleep(1)
        report["second_healthy_status"] = repeated["status"]
        report["second_healthy_seconds"] = time.monotonic() - repeat_start
        assert repeated["status"] == "complete"
    report["failed_status"] = failed["status"]
    report["healthy_status"] = complete["status"]
    report["fail_then_success"] = (
        failed["status"] == "failed" and complete["status"] == "complete"
    )
    report["same_worker_process"] = worker_id == state.control(KIND).get("worker_id")
    report["pending_after"] = int(state.control(KIND)["pending"])
    report["total_seconds"] = time.monotonic() - start
    report["validated_result"] = bool(complete.get("result"))
    if (
        not report["fail_then_success"]
        or not report["same_worker_process"]
        or report["pending_after"]
    ):
        raise AssertionError("Worker failure-isolation contract failed")
finally:
    log = subprocess.check_output(
        ["docker", "logs", container], stderr=subprocess.STDOUT, text=True
    )
    report["embedding_model_loads"] = log.count(
        "Loading SentenceTransformer model from"
    )
    report["models_reused"] = report["embedding_model_loads"] == 1
    (ROOT / ".artifacts" / ("local-" + KIND + "-worker.log")).write_text(log)
    subprocess.run(
        ["docker", "stop", "--time", "20", container],
        stdout=subprocess.DEVNULL,
        check=False,
    )
    subprocess.run(
        ["docker", "rm", "--volumes", container], stdout=subprocess.DEVNULL, check=False
    )
    path = ROOT / ".artifacts/local-workers.json"
    merged = json.loads(path.read_text()) if path.exists() else {}
    merged[KIND] = report
    path.write_text(json.dumps(merged, indent=2))
print(json.dumps(report))
