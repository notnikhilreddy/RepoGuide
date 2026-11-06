"""Read-only inventory of RepoGuide resources; never deletes or prints secrets."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = {
        k: v["value"]
        for k, v in json.loads(
            subprocess.check_output(
                [
                    "terraform",
                    "-chdir=" + str(ROOT / "infra/terraform"),
                    "output",
                    "-json",
                ],
                text=True,
            )
        ).items()
    }
    session = boto3.Session(profile_name="repoguide", region_name="us-east-2")
    ecs = session.client("ecs")
    ecr = session.client("ecr")
    s3 = session.client("s3")
    services = ecs.describe_services(
        cluster=out["ecs_cluster"], services=list(out["ecs_services"].values())
    )["services"]
    ecr_images = {}
    for role, uri in out["ecr_workers"].items():
        repository = uri.split("/", 1)[1]
        images = []
        for page in ecr.get_paginator("describe_images").paginate(
            repositoryName=repository
        ):
            images.extend(
                {
                    k: x.get(k)
                    for k in [
                        "imageDigest",
                        "imageTags",
                        "imageSizeInBytes",
                        "imagePushedAt",
                    ]
                }
                for x in page["imageDetails"]
            )
        ecr_images[role] = images
    prefix = out["ecs_cluster"].removesuffix("-cluster")
    lambdas = [
        {k: f[k] for k in ["FunctionName", "PackageType", "MemorySize", "LastModified"]}
        for p in session.client("lambda").get_paginator("list_functions").paginate()
        for f in p["Functions"]
        if f["FunctionName"].startswith(prefix)
    ]
    logs = [
        {k: g.get(k) for k in ["logGroupName", "retentionInDays", "storedBytes"]}
        for p in session.client("logs")
        .get_paginator("describe_log_groups")
        .paginate(logGroupNamePrefix="/aws/")
        for g in p["logGroups"]
        if prefix in g["logGroupName"]
    ]
    releases = []
    job_count = 0
    job_bytes = 0
    for p in s3.get_paginator("list_objects_v2").paginate(
        Bucket=out["artifact_bucket"], Prefix="releases/", Delimiter="/"
    ):
        releases.extend(x["Prefix"] for x in p.get("CommonPrefixes", []))
    for p in s3.get_paginator("list_objects_v2").paginate(
        Bucket=out["artifact_bucket"], Prefix="jobs/"
    ):
        for x in p.get("Contents", []):
            job_count += 1
            job_bytes += x["Size"]
    budgets = session.client("budgets", region_name="us-east-1").describe_budgets(
        AccountId=session.client("sts").get_caller_identity()["Account"]
    )["Budgets"]
    report = {
        "observed_at": int(time.time()),
        "read_only": True,
        "services": [
            {
                k: s[k]
                for k in [
                    "serviceName",
                    "desiredCount",
                    "runningCount",
                    "pendingCount",
                    "taskDefinition",
                ]
            }
            for s in services
        ],
        "tasks": ecs.list_tasks(cluster=out["ecs_cluster"])["taskArns"],
        "ecr": ecr_images,
        "lambdas": lambdas,
        "logs": logs,
        "release_prefixes": releases,
        "job_artifacts": {"objects": job_count, "bytes": job_bytes},
        "s3_lifecycle": s3.get_bucket_lifecycle_configuration(
            Bucket=out["artifact_bucket"]
        )["Rules"],
        "ecr_lifecycle": {
            k: json.loads(
                ecr.get_lifecycle_policy(repositoryName=v.split("/", 1)[1])[
                    "lifecyclePolicyText"
                ]
            )
            for k, v in out["ecr_workers"].items()
        },
        "budgets": [
            {k: b.get(k) for k in ["BudgetName", "BudgetLimit", "TimeUnit"]}
            for b in budgets
        ],
    }
    (ROOT / ".artifacts/product-resource-inventory.json").write_text(
        json.dumps(report, indent=2, default=str)
    )
    print(
        json.dumps(
            {
                "owned_services": len(services),
                "running_tasks": len(report["tasks"]),
                "images_per_role": {k: len(v) for k, v in ecr_images.items()},
                "lambda_functions": len(lambdas),
                "release_archives": len(releases),
                "job_artifact_bytes": job_bytes,
                "budgets": report["budgets"],
            }
        )
    )


if __name__ == "__main__":
    main()
