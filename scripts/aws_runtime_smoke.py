"""Real signed-token AWS checks; no judge/evaluation requests or invitations.

Baseline stops both workers. Final may leave them explicitly enabled only for
the separately monitored real idle test. Credentials and raw logs stay private.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3
import httpx

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / ".artifacts"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--phase", choices=["baseline", "final"], required=True)
parser.add_argument("--leave-running-for-idle-test", action="store_true")
parser.add_argument("--temporary-admin", action="store_true")
args = parser.parse_args()
outputs = json.loads(
    subprocess.check_output(
        ["terraform", "-chdir=" + str(ROOT / "infra/terraform"), "output", "-json"],
        text=True,
    )
)
out = {k: v["value"] for k, v in outputs.items()}
boto3.setup_default_session(profile_name="repoguide", region_name="us-east-2")
cognito, ecs = boto3.client("cognito-idp"), boto3.client("ecs")
pool, client_id = out["user_pool_id"], out["cognito_client_id"]
private = ART / "private"
private.mkdir(exist_ok=True, mode=0o700)
credentials_file = private / (
    "cognito-smoke-admin.json" if args.temporary_admin else "cognito-admin.json"
)
email = (
    "smoke-admin-" + uuid.uuid4().hex[:8] + "@example.invalid"
    if args.temporary_admin
    else "nikhilreddy.maligireddy2@gmail.com"
)
if not args.temporary_admin and (
    credentials_file.exists()
    and json.loads(credentials_file.read_text()).get("user_pool_id") == pool
):
    password = json.loads(credentials_file.read_text())["password"]
else:
    password = secrets.token_urlsafe(28) + "Aa9!"
    cognito.admin_create_user(
        UserPoolId=pool,
        Username=email,
        MessageAction="SUPPRESS",
        UserAttributes=[
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
        ],
    )
    cognito.admin_set_user_password(
        UserPoolId=pool, Username=email, Password=password, Permanent=True
    )
    credentials_file.write_text(
        json.dumps(
            {"username": email, "password": password, "user_pool_id": pool}, indent=2
        )
    )
    credentials_file.chmod(0o600)
cognito.admin_add_user_to_group(
    UserPoolId=pool, Username=email, GroupName="repoguide-admins"
)


def authenticate(username, password):
    return cognito.admin_initiate_auth(
        UserPoolId=pool,
        ClientId=client_id,
        AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": password},
    )["AuthenticationResult"]


tokens = authenticate(email, password)
subject = json.loads(
    base64.urlsafe_b64decode(tokens["AccessToken"].split(".")[1] + "==")
)["sub"]
http = httpx.Client(base_url=out["api_url"], timeout=20)
report = {
    "live_aws": True,
    "live_cognito": True,
    "phase": args.phase,
    "release_id": json.loads((ART / "release-manifest.json").read_text())["release_id"],
    "started_at": datetime.now(timezone.utc).isoformat(),
    "checks": {},
    "timings": {},
}
viewer = "smoke-" + uuid.uuid4().hex[:10] + "@example.invalid"
success = False


def save():
    (ART / ("aws-" + args.phase + "-smoke.json")).write_text(
        json.dumps(report, indent=2)
    )


def request(method, path, body=None, *, token=None, expected=None, headers=None):
    auth = {"Authorization": "Bearer " + (token or tokens["AccessToken"])}
    if headers:
        auth.update(headers)
    if expected is None:
        expected = 202 if method == "POST" else 200
    start = time.monotonic()
    response = http.request(method, path, json=body, headers=auth)
    if response.status_code != expected:
        raise AssertionError(
            f"{method} {path}: expected {expected}, got {response.status_code}"
        )
    report["timings"][method + " " + path] = round(time.monotonic() - start, 3)
    return response.json() if response.content else None


def status():
    return request("GET", "/api/compute/status")["workers"]


def wait_ready(kind):
    start = time.monotonic()
    while time.monotonic() - start < 1200:
        ctl = status()[kind]
        if ctl.get("observed_state") == "ready":
            report["timings"][kind + "_ready_seconds"] = round(
                time.monotonic() - start, 2
            )
            return ctl
        if ctl.get("observed_state") == "failed":
            raise AssertionError(kind + " failed readiness")
        time.sleep(10)
    raise TimeoutError(kind + " readiness deadline")


def submit(path, body):
    return request("POST", path, body, headers={"Idempotency-Key": str(uuid.uuid4())})


def wait_job(job_id, expected="complete"):
    start = time.monotonic()
    while time.monotonic() - start < 1200:
        job = request("GET", "/api/ui/jobs/" + job_id)
        if job["status"] in {"complete", "failed", "cancelled"}:
            if job["status"] != expected:
                raise AssertionError(
                    "Unexpected terminal job status: "
                    + job["status"]
                    + " / "
                    + str(job.get("error_code"))
                )
            return job, round(time.monotonic() - start, 2)
        time.sleep(3)
    raise TimeoutError("Job deadline")


def services():
    return ecs.describe_services(
        cluster=out["ecs_cluster"], services=list(out["ecs_services"].values())
    )["services"]


def stop_all():
    for kind in ["answer", "index"]:
        try:
            request("POST", "/api/compute/" + kind + "/stop", {"force": True})
        except Exception:
            ecs.update_service(
                cluster=out["ecs_cluster"],
                service=out["ecs_services"][kind],
                desiredCount=0,
            )
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        if all(
            s["desiredCount"] == s["runningCount"] == s["pendingCount"] == 0
            for s in services()
        ):
            return
        time.sleep(5)
    raise TimeoutError("Workers did not stop")


try:
    health = http.get("/health")
    assert health.status_code == 200 and health.json()["status"] == "ok"
    assert http.get("/api/ui/repositories").status_code == 401
    request("GET", "/api/ui/repositories", token=tokens["IdToken"], expected=403)
    assert (
        http.get("/api/compute/status", headers={"x-admin": "true"}).status_code == 401
    )
    cors = http.options(
        "/api/compute/answer/start",
        headers={
            "Origin": "https://repo-guide-five.vercel.app",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
        },
    )
    assert (
        cors.status_code in {200, 204}
        and cors.headers.get("access-control-allow-origin")
        == "https://repo-guide-five.vercel.app"
    )
    assert all(s["desiredCount"] == s["runningCount"] == 0 for s in services())
    repositories = request("GET", "/api/ui/repositories")
    repo = next(r for r in repositories if "notnikhilreddy/RepoGuide" in r["url"])
    repo_id = repo["id"]
    request("GET", "/ready")
    request("GET", "/api/ui/repositories/" + repo_id + "/overview")
    files = request("GET", "/api/ui/repositories/" + repo_id + "/files")
    assert files
    path = files[0]["path"]
    from urllib.parse import quote

    request("GET", "/api/ui/repositories/" + repo_id + "/file?path=" + quote(path))
    request(
        "GET",
        "/api/ui/repositories/" + repo_id + "/symbols-in-file?path=" + quote(path),
    )
    request("GET", "/repositories/" + repo_id + "/graph")
    request("GET", "/repositories/" + repo_id + "/dependencies")
    request("GET", "/api/ui/evaluations")
    assert all(s["desiredCount"] == s["runningCount"] == 0 for s in services())
    report["checks"]["browsing_workers_zero"] = True
    cognito.admin_create_user(
        UserPoolId=pool,
        Username=viewer,
        MessageAction="SUPPRESS",
        UserAttributes=[
            {"Name": "email", "Value": viewer},
            {"Name": "email_verified", "Value": "true"},
        ],
    )
    viewer_password = secrets.token_urlsafe(25) + "Aa9!"
    cognito.admin_set_user_password(
        UserPoolId=pool, Username=viewer, Password=viewer_password, Permanent=True
    )
    viewer_token = authenticate(viewer, viewer_password)["AccessToken"]
    request("POST", "/api/compute/answer/start", {}, token=viewer_token, expected=403)
    request("POST", "/api/compute/index/start", {}, token=viewer_token, expected=403)
    report["checks"]["unauthorized_controls_denied"] = True
    for kind in ["answer", "index"]:
        request("POST", "/api/compute/" + kind + "/start", {})
        if kind == "answer":
            index_service = next(
                s
                for s in services()
                if s["serviceName"] == out["ecs_services"]["index"]
            )
            assert index_service["desiredCount"] == 0
        wait_ready(kind)
        save()
    before = status()
    report["checks"]["independent_admin_controls"] = True
    if args.phase == "final":
        for k in ["JOB_TABLE", "ECS_CLUSTER"]:
            os.environ["REPOGUIDE_" + k] = out[
                "job_table" if k == "JOB_TABLE" else "ecs_cluster"
            ]
        for kind in ["answer", "index"]:
            for suffix, value in [
                ("SERVICE", out["ecs_services"][kind]),
                ("QUEUE_URL", out["queues"][kind]),
                ("DLQ_URL", out["deadletter_queues"][kind]),
            ]:
                os.environ["REPOGUIDE_" + kind.upper() + "_" + suffix] = value
        from repoguide import cloud_state as state

        state.clients.cache_clear()
        for kind, payload in [
            ("answer", {"unexpected_argument": True}),
            ("index", {"url": "file:///etc/passwd"}),
        ]:
            bad = state.submit(kind, subject, payload, str(uuid.uuid4()))
            report.setdefault("failed_test_job_ids", {})[kind] = bad["id"]
            wait_job(bad["id"], "failed")
            report["checks"][kind + "_failed_job_isolated"] = True
    ask = {
        "repo_id": repo_id,
        "question": "How does index_repository commit database changes and roll back failures?",
        "docs_policy": "never",
        "retrieval_mode": "hybrid",
        "answer_depth": "standard",
        "top_k": 8,
    }
    if args.phase == "final":
        ask["question"] = (
            "How does index_repository save source snapshots and handle failed database commits?"
        )
    answer_job = submit("/ask-jobs", ask)
    result, elapsed = wait_job(answer_job["id"])
    assert (
        result["result"]["status"] in {"answered", "partial"}
        and result["result"]["verified_labels"]
    )
    report["timings"]["answer_job_seconds"] = elapsed
    report["checks"]["live_answer_with_validated_citations"] = True
    if args.phase == "final":
        cached, _ = wait_job(submit("/ask-jobs", ask)["id"])
        assert cached["result"]["cached"] is True
        request(
            "GET", "/api/ui/jobs/" + answer_job["id"], token=viewer_token, expected=404
        )
        report["checks"]["upstash_cache_hit"] = True
        report["checks"]["job_ownership"] = True
        documented, _ = wait_job(
            submit(
                "/ask-jobs",
                {
                    **ask,
                    "question": "Explain the SQLAlchemy session rollback pattern used in index_repository with official SQLAlchemy documentation.",
                    "docs_policy": "always",
                },
            )["id"]
        )
        report["checks"]["context7_cloud_documentation"] = bool(
            documented["result"].get("docs_sources")
        )
        if not report["checks"]["context7_cloud_documentation"]:
            raise AssertionError(
                "Hosted Context7 lookup did not produce documentation evidence"
            )
        missing, _ = wait_job(
            submit(
                "/ask-jobs",
                {
                    **ask,
                    "question": "What open GitHub issues and PRs have maintainers filed about repository indexing rollback?",
                    "docs_policy": "auto",
                },
            )["id"]
        )
        assert missing["result"]["status"] in {"partial", "insufficient_evidence"}
        report["checks"]["github_unavailable_truthful_partial"] = True
    index_job = submit(
        "/api/ui/index-jobs",
        {
            "url": "https://github.com/pallets/markupsafe",
            "force": args.phase == "final",
        },
    )
    indexed, elapsed = wait_job(index_job["id"])
    report["timings"]["index_job_seconds"] = elapsed
    report["checks"]["live_index_persisted"] = True
    report["indexed_test_repo_id"] = indexed["result"]["repo_id"]
    if args.phase == "final":
        wait_job(
            submit(
                "/api/ui/index-jobs", {"url": "https://github.com/pallets/markupsafe"}
            )["id"]
        )
    after = status()
    assert all(
        before[k]["worker_id"] == after[k]["worker_id"] and after[k]["pending"] == 0
        for k in ["answer", "index"]
    )
    report["checks"]["same_process_after_jobs"] = True
    report["workers"] = {
        k: {
            field: after[k].get(field)
            for field in [
                "worker_id",
                "startup_ms",
                "release_id",
                "model_version",
                "pending",
            ]
        }
        for k in ["answer", "index"]
    }
    task_arns = ecs.list_tasks(cluster=out["ecs_cluster"], desiredStatus="RUNNING")[
        "taskArns"
    ]
    tasks = ecs.describe_tasks(cluster=out["ecs_cluster"], tasks=task_arns)["tasks"]
    manifest = json.loads((ART / "release-manifest.json").read_text())
    for task in tasks:
        for container in task["containers"]:
            assert (
                container["imageDigest"]
                == manifest["images"][container["name"]].split("@", 1)[1]
            )
    report["tasks"] = [
        {
            "cpu": t["cpu"],
            "memory": t["memory"],
            "images": [
                {"name": c["name"], "digest": c.get("imageDigest")}
                for c in t["containers"]
            ],
        }
        for t in tasks
    ]
    success = True
    report["passed"] = True
except Exception as exc:
    report["passed"] = False
    report["error_type"] = type(exc).__name__
    report["error"] = (
        str(exc)[:300]
        if isinstance(exc, (AssertionError, TimeoutError))
        else type(exc).__name__
    )
    raise
finally:
    if not success or not args.leave_running_for_idle_test:
        stop_all()
        report["workers_stopped"] = True
    else:
        report["workers_intentionally_enabled_for_idle_test"] = True
    try:
        cognito.admin_delete_user(UserPoolId=pool, Username=viewer)
    except cognito.exceptions.UserNotFoundException:
        pass
    if args.temporary_admin:
        cognito.admin_delete_user(UserPoolId=pool, Username=email)
        credentials_file.unlink(missing_ok=True)
    save()
    print(
        json.dumps(
            {
                "phase": args.phase,
                "passed": success,
                "workers_stopped": report.get("workers_stopped", False),
                "error": report.get("error"),
            }
        ),
        flush=True,
    )
