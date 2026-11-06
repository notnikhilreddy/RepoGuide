"""Drill retained task-configuration rollback and restore with compute at zero.

Does not claim a historical whole-release or quality-baseline rollback.
"""

import json
import subprocess
from pathlib import Path

import boto3
import httpx

root = Path(__file__).resolve().parents[1]
art = root / ".artifacts"
out = {
    k: v["value"]
    for k, v in json.loads(
        subprocess.check_output(
            ["terraform", "-chdir=" + str(root / "infra/terraform"), "output", "-json"]
        )
    ).items()
}
session = boto3.Session(profile_name="repoguide", region_name="us-east-2")
ecs = session.client("ecs")
services = out["ecs_services"]
previous = json.loads((art / "private/native-4g-taskdefs.json").read_text())
current = {
    s["serviceName"]: s["taskDefinition"]
    for s in ecs.describe_services(
        cluster=out["ecs_cluster"], services=list(services.values())
    )["services"]
}
report = {
    "release_id": json.loads((art / "release-manifest.json").read_text())["release_id"],
    "scope": "task-definition configuration rollback and restore, compute held at zero",
    "historical_approved_full_release_rollback": False,
    "steps": [],
}


def check_zero(expected):
    actual = ecs.describe_services(
        cluster=out["ecs_cluster"], services=list(services.values())
    )["services"]
    assert len(actual) == 2
    for service in actual:
        assert service["taskDefinition"] == expected[service["serviceName"]]
        assert (
            service["desiredCount"]
            == service["runningCount"]
            == service["pendingCount"]
            == 0
        )


try:
    check_zero(current)
    for name, definition in previous.items():
        assert (
            ecs.describe_task_definition(taskDefinition=definition)["taskDefinition"][
                "status"
            ]
            == "ACTIVE"
        )
        ecs.update_service(
            cluster=out["ecs_cluster"],
            service=name,
            taskDefinition=definition,
            desiredCount=0,
        )
    check_zero(previous)
    report["steps"].append(
        "retained measured task definitions restored with both services zero"
    )
    with httpx.Client(timeout=20) as http:
        response = http.get(out["api_url"] + "/health")
        response.raise_for_status()
        assert response.json()["status"] == "ok"
    report["steps"].append("live API health stayed available during rollback")
finally:
    for name, definition in current.items():
        ecs.update_service(
            cluster=out["ecs_cluster"],
            service=name,
            taskDefinition=definition,
            desiredCount=0,
        )
    check_zero(current)
    report["steps"].append(
        "current exact-digest task definitions restored with both services zero"
    )
    report["restored_current_definitions"] = True
    (art / "aws-component-rollback.json").write_text(json.dumps(report, indent=2))
report["passed"] = True
(art / "aws-component-rollback.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report))
