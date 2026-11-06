"""Observe real idle shutdown and minute-59 reset without modifying clocks.

Requires both workers explicitly enabled and ready. Maximum duration 150 minutes;
all exits force both services to zero. Only one bounded functional answer is sent.
"""

import json
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3
import httpx

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / ".artifacts"
out = {
    k: v["value"]
    for k, v in json.loads(
        subprocess.check_output(
            ["terraform", "-chdir=" + str(ROOT / "infra/terraform"), "output", "-json"],
            text=True,
        )
    ).items()
}
credentials = json.loads((ART / "private/cognito-admin.json").read_text())
session = boto3.Session(profile_name="repoguide", region_name="us-east-2")
cognito, ecs = session.client("cognito-idp"), session.client("ecs")
http = httpx.Client(base_url=out["api_url"], timeout=20)
auth_time, token = 0, ""
started = time.monotonic()
report = {
    "live_aws": True,
    "real_wall_clock": True,
    "status": "running",
    "started_at": datetime.now(timezone.utc).isoformat(),
    "release_id": json.loads((ART / "release-manifest.json").read_text())["release_id"],
    "samples": [],
}


def request(method, path, body=None):
    global auth_time, token
    if time.monotonic() - auth_time > 1800 or not token:
        token = cognito.admin_initiate_auth(
            UserPoolId=out["user_pool_id"],
            ClientId=out["cognito_client_id"],
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": credentials["username"],
                "PASSWORD": credentials["password"],
            },
        )["AuthenticationResult"]["AccessToken"]
        auth_time = time.monotonic()
    if method == "POST" and path == "/ask-jobs":
        from acceptance_budget import reserve_answer

        reserve_answer("real-minute-59-idle-reset")
    response = http.request(
        method,
        path,
        json=body,
        headers={
            "Authorization": "Bearer " + token,
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    if response.status_code not in {200, 202}:
        raise RuntimeError("Idle check HTTP " + str(response.status_code))
    return response.json()


def save():
    report["elapsed_seconds"] = round(time.monotonic() - started, 1)
    (ART / "aws-idle-verification.json").write_text(json.dumps(report, indent=2))


try:
    repositories = request("GET", "/api/ui/repositories")
    repo = next(r for r in repositories if "notnikhilreddy/RepoGuide" in r["url"])
    original = None
    reset_sent = False
    reset_job = None
    new_idle = None
    stopped = {}
    while time.monotonic() - started < 9000:
        now = int(time.time())
        workers = request("GET", "/api/compute/status")["workers"]
        sample = {
            "time": now,
            "elapsed_seconds": round(time.monotonic() - started, 1),
            "workers": {
                k: {
                    field: workers[k].get(field)
                    for field in [
                        "desired_state",
                        "observed_state",
                        "idle_since",
                        "pending",
                        "queued",
                        "inflight",
                        "delayed",
                        "last_heartbeat",
                    ]
                }
                for k in ["answer", "index"]
            },
        }
        report["samples"].append(sample)
        if original is None:
            if not all(workers[k].get("idle_since") for k in ["answer", "index"]):
                if time.monotonic() - started > 180:
                    raise TimeoutError("Workers did not enter idle state")
                save()
                time.sleep(15)
                continue
            original = {k: int(workers[k]["idle_since"]) for k in ["answer", "index"]}
            report["original_idle_since"] = original
            assert all(
                workers[k]["desired_state"] == "on"
                and workers[k]["observed_state"] == "ready"
                for k in original
            )
        if not reset_sent and now >= original["answer"] + 3540:
            assert now < original["answer"] + 3600, "Missed minute-59 window"
            reset_job = request(
                "POST",
                "/ask-jobs",
                {
                    "repo_id": repo["id"],
                    "question": "What does index_repository return when the same commit is already indexed?",
                    "docs_policy": "never",
                    "retrieval_mode": "hybrid",
                    "answer_depth": "concise",
                    "top_k": 5,
                },
            )["id"]
            reset_sent = True
            report["reset_accepted_at"] = now
            report["reset_elapsed_idle_seconds"] = now - original["answer"]
            print(
                "Minute-59 functional answer accepted; observing the new idle window.",
                flush=True,
            )
        if reset_sent and new_idle is None:
            job = request("GET", "/api/ui/jobs/" + reset_job)
            if job["status"] == "failed":
                raise RuntimeError("Minute-59 job failed")
            if job["status"] == "complete" and workers["answer"].get("idle_since"):
                new_idle = int(workers["answer"]["idle_since"])
                assert new_idle > original["answer"] + 3500
                report["new_answer_idle_since"] = new_idle
        if (
            reset_sent
            and now >= original["answer"] + 3660
            and not report.get("minute_59_reset_prevented_old_deadline_stop")
        ):
            assert workers["answer"]["desired_state"] == "on", (
                "Answer stopped at the old deadline despite accepted work"
            )
            report["minute_59_reset_prevented_old_deadline_stop"] = True
        for kind in ["answer", "index"]:
            if kind in stopped:
                assert workers[kind]["desired_state"] == "off", (
                    "Browsing restarted compute"
                )
                continue
            if workers[kind]["desired_state"] == "off":
                since = new_idle if kind == "answer" else original["index"]
                assert since is not None and 3600 <= now - since <= 3780, (
                    "Unexpected idle shutdown interval"
                )
                stopped[kind] = now
                report[kind + "_observed_idle_seconds"] = now - since
                print(
                    kind + " stopped after its real continuous idle window.", flush=True
                )
        save()
        if len(stopped) == 2:
            report.update(
                status="passed",
                idle_sixty_real_minutes=True,
                minute_59_reset=True,
                browsing_did_not_reset_idle=True,
            )
            break
        time.sleep(15)
    else:
        raise TimeoutError("Real idle test exceeded the spending safety window")
except Exception as exc:
    report.update(status="failed", error_type=type(exc).__name__)
    if isinstance(exc, (AssertionError, TimeoutError)):
        report["error"] = str(exc)[:200]
    raise
finally:
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
        services = ecs.describe_services(
            cluster=out["ecs_cluster"], services=list(out["ecs_services"].values())
        )["services"]
        if all(
            s["desiredCount"] == s["runningCount"] == s["pendingCount"] == 0
            for s in services
        ):
            report["final_services_zero"] = True
            break
        time.sleep(5)
    save()
    print(
        json.dumps(
            {
                k: report.get(k)
                for k in ["status", "elapsed_seconds", "final_services_zero"]
            }
        ),
        flush=True,
    )
