"""Finish real idle acceptance after a local observer sleep interrupted polling.

Keep the failed original report. Its actual minute-59 reset and AWS's Index
stopping timestamp remain evidence. Observe a separately started Answer for a
full real idle hour; never infer a shutdown time from when this laptop wakes.
This does not claim one continuous two-hour Answer-worker observation.
"""

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
import httpx

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / ".artifacts"
original = json.loads((ART / "aws-idle-observer-interrupted.json").read_text())
index = json.loads((ART / "aws-idle-index-authoritative.json").read_text())
start = json.loads((ART / "aws-idle-repeat-start.json").read_text())
manifest = json.loads((ART / "release-manifest.json").read_text())
assert all(r["release_id"] == manifest["release_id"] for r in [original, index, start])
assert original["minute_59_reset_prevented_old_deadline_stop"] is True
assert 3540 <= original["reset_elapsed_idle_seconds"] < 3600
assert index["passed"] and 3600 <= index["observed_idle_seconds"] <= 3780
out = {
    k: v["value"]
    for k, v in json.loads(
        subprocess.check_output(
            ["terraform", "-chdir=" + str(ROOT / "infra/terraform"), "output", "-json"]
        )
    ).items()
}
session = boto3.Session(profile_name="repoguide", region_name="us-east-2")
cognito, ecs = session.client("cognito-idp"), session.client("ecs")
credentials = json.loads((ART / "private/cognito-admin.json").read_text())
http = httpx.Client(base_url=out["api_url"], timeout=30)
auth_time, token = 0, ""
began = time.time()
report = {
    "release_id": manifest["release_id"],
    "live_aws": True,
    "real_wall_clock": True,
    "status": "running",
    "started_at": datetime.now(timezone.utc).isoformat(),
    "verification_method": "separate real observations with AWS-authoritative shutdown timestamps",
    "interrupted_observation": "aws-idle-observer-interrupted.json",
    "index_shutdown": index,
    "minute_59_reset_observation": {
        k: original[k]
        for k in [
            "original_idle_since",
            "reset_accepted_at",
            "reset_elapsed_idle_seconds",
            "new_answer_idle_since",
            "minute_59_reset_prevented_old_deadline_stop",
        ]
    },
    "minute_59_reset_prevented_old_deadline_stop": True,
    "continuous_two_hour_worker_lifetime_observed": False,
    "additional_model_generation_calls": 0,
    "samples": [],
}


def request(method, path, body=None):
    global auth_time, token
    if not token or time.time() - auth_time > 1800:
        token = cognito.admin_initiate_auth(
            UserPoolId=out["user_pool_id"],
            ClientId=out["cognito_client_id"],
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": credentials["username"],
                "PASSWORD": credentials["password"],
            },
        )["AuthenticationResult"]["AccessToken"]
        auth_time = time.time()
    response = http.request(
        method, path, json=body, headers={"Authorization": "Bearer " + token}
    )
    response.raise_for_status()
    return response.json()


def save():
    report["elapsed_seconds"] = round(time.time() - began, 1)
    (ART / "aws-idle-verification.json").write_text(json.dumps(report, indent=2))


try:
    idle_since, task_arn, worker_id = None, None, None
    while time.time() - began < 5100:
        workers = request("GET", "/api/compute/status")["workers"]
        answer = workers["answer"]
        assert workers["index"]["desired_state"] == "off", "Index unexpectedly enabled"
        assert answer["observed_state"] != "failed", "Answer worker failed"
        report["samples"].append(
            {
                "time": int(time.time()),
                "workers": {
                    role: {
                        k: workers[role].get(k)
                        for k in [
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
                    for role in ["answer", "index"]
                },
            }
        )
        if idle_since is None and answer.get("idle_since"):
            assert answer["observed_state"] == "ready"
            idle_since, worker_id = int(answer["idle_since"]), answer["worker_id"]
            tasks = ecs.list_tasks(
                cluster=out["ecs_cluster"], serviceName=out["ecs_services"]["answer"]
            )["taskArns"]
            assert len(tasks) == 1
            task_arn = tasks[0]
            report.update(
                answer_repeat_idle_since=idle_since, answer_repeat_worker_id=worker_id
            )
            print("Answer ready; observing its complete real idle hour.", flush=True)
        elif idle_since is not None and answer["desired_state"] == "on":
            assert answer.get("idle_since") == idle_since, (
                "Unexpected work reset the controlled window"
            )
            assert answer.get("worker_id") == worker_id, "Worker process changed"
        if answer["desired_state"] == "off":
            assert idle_since is not None and task_arn is not None
            task = ecs.describe_tasks(cluster=out["ecs_cluster"], tasks=[task_arn])[
                "tasks"
            ][0]
            if not task.get("stoppingAt"):
                save()
                time.sleep(15)
                continue
            elapsed = task["stoppingAt"].timestamp() - idle_since
            assert 3600 <= elapsed <= 3780, "AWS shutdown outside the idle-hour window"
            assert task["stopCode"] == "ServiceSchedulerInitiated"
            assert any(
                c.get("imageDigest") == manifest["images"]["answer"].split("@")[-1]
                for c in task["containers"]
            )
            report.update(
                status="passed",
                answer_observed_idle_seconds=round(elapsed, 3),
                index_observed_idle_seconds=index["observed_idle_seconds"],
                answer_shutdown={
                    "task_arn": task_arn,
                    "stopping_at": task["stoppingAt"].isoformat(),
                    "stop_code": task["stopCode"],
                },
                idle_sixty_real_minutes=True,
                minute_59_reset=True,
                browsing_did_not_reset_idle=True,
            )
            break
        save()
        time.sleep(15)
    else:
        raise TimeoutError("Idle completion exceeded its real-wall-clock safety window")
except BaseException as exc:
    report.update(status="failed", error_type=type(exc).__name__, error=str(exc)[:200])
    raise
finally:
    for role in ["answer", "index"]:
        try:
            request("POST", "/api/compute/" + role + "/stop", {"force": True})
        except Exception:
            ecs.update_service(
                cluster=out["ecs_cluster"],
                service=out["ecs_services"][role],
                desiredCount=0,
            )
    deadline = time.time() + 300
    while time.time() < deadline:
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
