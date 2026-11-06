"""Read back zero compute, temporary-access cleanup and remaining alert state."""

import json
import subprocess
import time
from pathlib import Path

import boto3

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
ecs, ec2, cognito, sqs = (
    session.client(k) for k in ["ecs", "ec2", "cognito-idp", "sqs"]
)
services = ecs.describe_services(
    cluster=out["ecs_cluster"], services=list(out["ecs_services"].values())
)["services"]
assert len(services) == 2
assert all(
    s["desiredCount"] == s["runningCount"] == s["pendingCount"] == 0 for s in services
)
assert not ecs.list_tasks(cluster=out["ecs_cluster"], desiredStatus="RUNNING")[
    "taskArns"
]
groups = list(
    {
        g
        for s in services
        for g in s["networkConfiguration"]["awsvpcConfiguration"]["securityGroups"]
    }
)
for _ in range(20):
    interfaces = ec2.describe_network_interfaces(
        Filters=[{"Name": "group-id", "Values": groups}]
    )["NetworkInterfaces"]
    if not interfaces:
        break
    time.sleep(5)
assert not interfaces, "Stopped task network interfaces still exist"
users = []
params = {"UserPoolId": out["user_pool_id"]}
while True:
    page = cognito.list_users(**params)
    users += page["Users"]
    if not page.get("PaginationToken"):
        break
    params["PaginationToken"] = page["PaginationToken"]
for user in users:
    email = next((a["Value"] for a in user["Attributes"] if a["Name"] == "email"), "")
    assert not (
        email.endswith("@example.invalid")
        and email.startswith(("smoke-", "rate-smoke-"))
    )
queues = {}
for kind in ["queues", "deadletter_queues"]:
    queues[kind] = {}
    for role, url in out[kind].items():
        attrs = sqs.get_queue_attributes(
            QueueUrl=url,
            AttributeNames=[
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
                "ApproximateNumberOfMessagesDelayed",
            ],
        )["Attributes"]
        assert all(int(v) == 0 for v in attrs.values())
        queues[kind][role] = {k: int(v) for k, v in attrs.items()}
client = cognito.describe_user_pool_client(
    UserPoolId=out["user_pool_id"], ClientId=out["cognito_client_id"]
)["UserPoolClient"]
assert set(client["CallbackURLs"]) == {
    "https://repo-guide-five.vercel.app/",
    "http://localhost:5173/",
}
assert set(client["LogoutURLs"]) == set(client["CallbackURLs"])
api_id = out["api_url"].split("//")[1].split(".")[0]
cors = session.client("apigatewayv2").get_api(ApiId=api_id)["CorsConfiguration"]
assert set(cors["AllowOrigins"]) == {
    "https://repo-guide-five.vercel.app",
    "http://localhost:5173",
}
assert json.loads((art / "vercel-bypass-cleanup.json").read_text())[
    "temporary_bypass_revoked"
]
assert json.loads((art / "smoke-dlq-cleanup.json").read_text())["passed"]
prefix = out["ecs_cluster"].removesuffix("-cluster")
alarms = session.client("cloudwatch").describe_alarms(AlarmNamePrefix=prefix)[
    "MetricAlarms"
]
subscriptions = session.client("sns").list_subscriptions()["Subscriptions"]
monitoring = {
    "alarms": [
        {k: a.get(k) for k in ["AlarmName", "StateValue", "StateReason"]}
        for a in alarms
    ],
    "sns_subscriptions": [
        {k: s.get(k) for k in ["Protocol", "SubscriptionArn"]} for s in subscriptions
    ],
}
(art / "aws-monitoring-review.json").write_text(json.dumps(monitoring, indent=2))
report = {
    "release_id": json.loads((art / "release-manifest.json").read_text())["release_id"],
    "passed": True,
    "both_services_desired_running_pending_zero": True,
    "running_tasks_zero": True,
    "worker_network_interfaces_zero": True,
    "task_public_ipv4_zero": True,
    "temporary_cognito_users_removed": True,
    "temporary_vercel_bypass_revoked": True,
    "temporary_preview_origin_removed": True,
    "queues_empty": queues,
    "owned_poison_diagnostics_archived": True,
    "remaining_manual_action": "Confirm AWS SNS alert subscription email"
    if any(x["SubscriptionArn"] == "PendingConfirmation" for x in subscriptions)
    else None,
    "alarm_states": {
        a["AlarmName"].removeprefix(prefix + "-"): a["StateValue"] for a in alarms
    },
}
(art / "deployment-cleanup.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report))
