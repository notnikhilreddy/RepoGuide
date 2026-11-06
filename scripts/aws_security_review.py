"""Read back deployed IAM/network configuration and simulate allowed/denied scopes."""

import json
import subprocess
from pathlib import Path

import boto3

root = Path(__file__).resolve().parents[1]
out = {
    k: v["value"]
    for k, v in json.loads(
        subprocess.check_output(
            ["terraform", "-chdir=" + str(root / "infra/terraform"), "output", "-json"],
            text=True,
        )
    ).items()
}
s = boto3.Session(profile_name="repoguide", region_name="us-east-2")
iam, ecs, ec2, sqs = (s.client(n) for n in ["iam", "ecs", "ec2", "sqs"])
prefix = out["ecs_cluster"].removesuffix("-cluster")
account = s.client("sts").get_caller_identity()["Account"]
base = "arn:aws:"
ssm = base + "ssm:us-east-2:" + account + ":parameter/repoguide/demo/"
queue = {
    k: sqs.get_queue_attributes(QueueUrl=v, AttributeNames=["QueueArn"])["Attributes"][
        "QueueArn"
    ]
    for k, v in out["queues"].items()
}
service = {
    k: base + "ecs:us-east-2:" + account + ":service/" + out["ecs_cluster"] + "/" + v
    for k, v in out["ecs_services"].items()
}
tests = {
    "api": [
        ("ssm:GetParameter", ssm + "api", True),
        ("ssm:GetParameter", ssm + "answer", False),
        ("ssm:GetParameter", ssm + "index", False),
        ("sqs:ReceiveMessage", queue["answer"], False),
        ("ecs:UpdateService", service["answer"], True),
    ],
    "answer": [
        ("ssm:GetParameter", ssm + "answer", True),
        ("ssm:GetParameter", ssm + "index", False),
        ("ssm:GetParameter", ssm + "api", False),
        ("sqs:ReceiveMessage", queue["answer"], True),
        ("sqs:ReceiveMessage", queue["index"], False),
        ("ecs:UpdateService", service["answer"], False),
    ],
    "index": [
        ("ssm:GetParameter", ssm + "index", True),
        ("ssm:GetParameter", ssm + "answer", False),
        ("sqs:ReceiveMessage", queue["index"], True),
        ("sqs:ReceiveMessage", queue["answer"], False),
        ("ecs:UpdateService", service["index"], False),
    ],
    "controller": [
        ("ssm:GetParameter", ssm + "api", False),
        ("sqs:ReceiveMessage", queue["answer"], False),
        ("ecs:UpdateService", service["index"], True),
    ],
    "ecs-execution": [
        ("ssm:GetParameter", ssm + "answer", False),
        ("sqs:ReceiveMessage", queue["answer"], False),
        ("ecs:UpdateService", service["index"], False),
    ],
}
report = {
    "live_aws": True,
    "iam_simulations": {},
    "policies_have_no_allow_all_actions": True,
    "simulation_scope": "deployed identity policies; actual runtime calls verified separately",
    "principal_simulation_note": "Principal-mode simulation denied the Organizations context; identity-policy simulations do not establish effective service permissions. Live API and worker calls are checked separately.",
}
raw_policies = {}
trust_checks = {}
for role, cases in tests.items():
    name = prefix + "-" + role
    deployed_role = iam.get_role(RoleName=name)["Role"]
    if role in {"answer", "index", "ecs-execution"}:
        trust = deployed_role["AssumeRolePolicyDocument"]["Statement"][0]
        assert trust["Principal"]["Service"] == "ecs-tasks.amazonaws.com"
        assert trust["Condition"]["StringEquals"]["aws:SourceAccount"] == account
        assert trust["Condition"]["ArnLike"]["aws:SourceArn"] == (
            "arn:aws:ecs:us-east-2:" + account + ":*"
        )
        trust_checks[role] = True
    policies = [
        iam.get_role_policy(RoleName=name, PolicyName=p)["PolicyDocument"]
        for p in iam.list_role_policies(RoleName=name)["PolicyNames"]
    ]
    raw_policies[role] = policies
    for policy in policies:
        for statement in policy["Statement"]:
            actions = statement["Action"]
            if isinstance(actions, str):
                actions = [actions]
            assert not any(a == "*" or a.endswith(":*") for a in actions)
    report["iam_simulations"][role] = []
    for action, resource, allowed in cases:
        evaluation = iam.simulate_custom_policy(
            PolicyInputList=[json.dumps(p) for p in policies],
            ActionNames=[action],
            ResourceArns=[resource],
        )["EvaluationResults"][0]
        actual = evaluation["EvalDecision"] == "allowed"
        assert actual == allowed, role + " / " + action + " scope mismatch"
        report["iam_simulations"][role].append(
            {"action": action, "expected_allowed": allowed, "matched": True}
        )
services = ecs.describe_services(
    cluster=out["ecs_cluster"], services=list(out["ecs_services"].values())
)["services"]
report["ecs_trust_account_and_region_scoped"] = trust_checks
report["task_hardening"] = {}
for service in services:
    definition = ecs.describe_task_definition(taskDefinition=service["taskDefinition"])[
        "taskDefinition"
    ]
    for container in definition["containerDefinitions"]:
        assert container["user"] == "10001:10001"
        assert container["readonlyRootFilesystem"] is True
        assert container["linuxParameters"]["capabilities"]["drop"] == ["ALL"]
        assert "@sha256:" in container["image"]
        report["task_hardening"][container["name"]] = {
            "non_root": True,
            "read_only_root": True,
            "all_linux_capabilities_dropped": True,
            "digest_pinned": True,
        }
group_ids = {
    g
    for svc in services
    for g in svc["networkConfiguration"]["awsvpcConfiguration"]["securityGroups"]
}
groups = ec2.describe_security_groups(GroupIds=list(group_ids))["SecurityGroups"]
for group in groups:
    assert not group["IpPermissions"]
    assert {
        (r["FromPort"], r["ToPort"], r["IpProtocol"])
        for r in group["IpPermissionsEgress"]
    } == {(443, 443, "tcp"), (5432, 5432, "tcp")}
    assert not ec2.describe_nat_gateways(
        Filter=[{"Name": "vpc-id", "Values": [group["VpcId"]]}]
    )["NatGateways"]
report.update(
    security_groups_no_ingress=True,
    security_groups_only_https_postgres_egress=True,
    no_nat_gateway=True,
)
bucket = s.client("s3")
block = bucket.get_public_access_block(Bucket=out["artifact_bucket"])[
    "PublicAccessBlockConfiguration"
]
assert all(block.values())
report["s3_all_public_access_blocked"] = True
(root / ".artifacts/private/aws-role-policies.json").write_text(
    json.dumps(raw_policies, indent=2)
)
(root / ".artifacts/aws-security-review.json").write_text(json.dumps(report, indent=2))
print(
    json.dumps(
        {
            "passed": True,
            "iam_scope_checks": sum(len(v) for v in tests.values()),
            "network_checked": True,
        }
    )
)
