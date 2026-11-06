"""Plan or retire verified-unused RepoGuide worker images and task revisions.

Current plus starting-release images/task definitions are retained. This never
changes services, indexes, chats, queues, secrets, Terraform state or backups.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]


def consumer_tasks(session):
    """Include dormant services and schedules, which also need recovery images."""
    ecs = session.client("ecs")
    protected = set()
    for page in ecs.get_paginator("list_clusters").paginate():
        for cluster in page["clusterArns"]:
            for page in ecs.get_paginator("list_services").paginate(cluster=cluster):
                arns = page["serviceArns"]
                for offset in range(0, len(arns), 10):
                    protected.update(
                        s["taskDefinition"]
                        for s in ecs.describe_services(
                            cluster=cluster, services=arns[offset : offset + 10]
                        )["services"]
                    )
            for page in ecs.get_paginator("list_tasks").paginate(cluster=cluster):
                arns = page["taskArns"]
                for offset in range(0, len(arns), 100):
                    protected.update(
                        t["taskDefinitionArn"]
                        for t in ecs.describe_tasks(
                            cluster=cluster, tasks=arns[offset : offset + 100]
                        )["tasks"]
                    )
    events = session.client("events")

    def buses():
        params = {}
        while True:
            page = events.list_event_buses(**params)
            yield page
            if not page.get("NextToken"):
                return
            params["NextToken"] = page["NextToken"]

    for page in buses():
        for bus in page["EventBuses"]:
            for rules in events.get_paginator("list_rules").paginate(
                EventBusName=bus["Name"]
            ):
                for rule in rules["Rules"]:
                    for targets in events.get_paginator(
                        "list_targets_by_rule"
                    ).paginate(EventBusName=bus["Name"], Rule=rule["Name"]):
                        protected.update(
                            t["EcsParameters"]["TaskDefinitionArn"]
                            for t in targets["Targets"]
                            if t.get("EcsParameters")
                        )
    scheduler = session.client("scheduler")
    for page in scheduler.get_paginator("list_schedules").paginate():
        for summary in page["Schedules"]:
            target = scheduler.get_schedule(
                Name=summary["Name"], GroupName=summary["GroupName"]
            )["Target"]
            if target.get("EcsParameters"):
                protected.add(target["EcsParameters"]["TaskDefinitionArn"])
    # Resolve unversioned schedule references before comparing revision ARNs.
    return {
        ecs.describe_task_definition(taskDefinition=task)["taskDefinition"][
            "taskDefinitionArn"
        ]
        for task in protected
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
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
    initial = json.loads((ROOT / ".artifacts/product-cloud-before.json").read_text())
    manifest = json.loads((ROOT / ".artifacts/release-manifest.json").read_text())
    session = boto3.Session(profile_name="repoguide", region_name="us-east-2")
    ecs = session.client("ecs")
    ecr = session.client("ecr")
    if session.client("sts").get_caller_identity()["Account"] != initial["account"]:
        raise ValueError("Account mismatch")
    services = ecs.describe_services(
        cluster=out["ecs_cluster"], services=list(out["ecs_services"].values())
    )["services"]
    definitions = {}
    for service in services:
        definition = ecs.describe_task_definition(
            taskDefinition=service["taskDefinition"]
        )["taskDefinition"]
        role = next(
            k for k, v in out["ecs_services"].items() if service["serviceName"] == v
        )
        if definition["containerDefinitions"][0]["image"] != manifest["images"][role]:
            raise ValueError("Only the newly verified live release may be cleaned up")
        definitions[role] = definition["taskDefinitionArn"]
    live_tasks = ecs.list_tasks(cluster=out["ecs_cluster"])["taskArns"]
    protected_tasks = set(definitions.values()) | {
        v["taskDefinition"] for v in initial["workers"].values()
    }
    consumers = consumer_tasks(session)
    protected_tasks.update(consumers)
    if live_tasks:
        protected_tasks |= {
            t["taskDefinitionArn"]
            for t in ecs.describe_tasks(cluster=out["ecs_cluster"], tasks=live_tasks)[
                "tasks"
            ]
        }
    protected_images = set(manifest["images"].values()) | {
        v["image"] for v in initial["workers"].values()
    }
    if manifest["quality"].get("deployment_equivalence"):
        measured = json.loads(
            (ROOT / ".artifacts/measured-6045/release-manifest.json").read_text()
        )
        if measured["source_sha256"] != manifest["quality"]["candidate_source"]:
            raise ValueError("Measured recovery release identity mismatch")
        for kind, image in measured["images"].items():
            if not image.startswith(out["ecr_workers"][kind] + "@sha256:"):
                raise ValueError("Measured recovery image is outside this stack")
            protected_images.add(image)
    lamb = session.client("lambda")
    for page in lamb.get_paginator("list_functions").paginate():
        for function in page["Functions"]:
            if function.get("PackageType") == "Image":
                code = lamb.get_function(FunctionName=function["FunctionName"])["Code"]
                if code.get("ResolvedImageUri"):
                    protected_images.add(code["ResolvedImageUri"])
    for task in protected_tasks:
        definition = ecs.describe_task_definition(taskDefinition=task)["taskDefinition"]
        protected_images |= {c["image"] for c in definition["containerDefinitions"]}
    # A consumer can use a mutable tag rather than an immutable digest. Resolve
    # every tag in our repositories; an unresolvable dependency blocks cleanup.
    for image in list(protected_images):
        for uri in out["ecr_workers"].values():
            if image.startswith(uri + ":"):
                detail = ecr.describe_images(
                    repositoryName=uri.split("/", 1)[1],
                    imageIds=[{"imageTag": image[len(uri) + 1 :]}],
                )["imageDetails"][0]
                protected_images.add(uri + "@" + detail["imageDigest"])
    remove_tasks = []
    raw_definitions = []
    for role, service_name in out["ecs_services"].items():
        for page in ecs.get_paginator("list_task_definitions").paginate(
            familyPrefix=service_name, status="ACTIVE"
        ):
            for arn in page["taskDefinitionArns"]:
                definition = ecs.describe_task_definition(taskDefinition=arn)[
                    "taskDefinition"
                ]
                if definition["family"] != service_name or arn in protected_tasks:
                    continue
                raw_definitions.append(definition)
                remove_tasks.append(arn)
    remove_images = []
    retained = []
    for role, uri in out["ecr_workers"].items():
        repository = uri.split("/", 1)[1]
        tags = ecr.list_tags_for_resource(
            resourceArn=ecr.describe_repositories(repositoryNames=[repository])[
                "repositories"
            ][0]["repositoryArn"]
        )["tags"]
        # Repository identity is already bound to this stack's Terraform output.
        # Record tags too; do not infer ownership from a broad name prefix.
        for page in ecr.get_paginator("describe_images").paginate(
            repositoryName=repository
        ):
            for image in page["imageDetails"]:
                row = {
                    "repository": repository,
                    "digest": image["imageDigest"],
                    "tags": image.get("imageTags", []),
                    "compressed_bytes": image["imageSizeInBytes"],
                    "repository_tags": tags,
                }
                if uri + "@" + image["imageDigest"] in protected_images:
                    retained.append(row)
                else:
                    remove_images.append(row)
    report = {
        "planned_at": int(time.time()),
        "release_id": manifest["release_id"],
        "apply": args.apply,
        "protected_task_definitions": sorted(protected_tasks),
        "protected_images": sorted(protected_images),
        "remove_task_definitions": remove_tasks,
        "remove_images": remove_images,
        "retained_images": retained,
        "logical_compressed_bytes_removed": sum(
            x["compressed_bytes"] for x in remove_images
        ),
        "storage_savings_note": "Logical image sizes share layers; actual billed ECR storage savings cannot be inferred by summing these sizes.",
        "retained": "All SQL/S3 conversations and indexes, secrets, state, database backups, release audit archives, current, measured and starting-release recovery images.",
    }
    if args.apply:
        from release_cloud import verify

        if verify()["status"] != "passed":
            raise ValueError("A passing measured quality gate is required")
        private = ROOT / ".artifacts/private/product-retired-task-definitions.json"
        if private.exists():
            raise ValueError(
                "A cleanup backup already exists; review instead of overwriting"
            )
        fd = os.open(private, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(raw_definitions, stream, default=str, indent=2)
        # Recheck running dependencies immediately before mutation.
        if consumer_tasks(session) != consumers:
            raise ValueError(
                "Cross-cluster or scheduled consumers changed during review"
            )
        latest = ecs.describe_services(
            cluster=out["ecs_cluster"], services=list(out["ecs_services"].values())
        )["services"]
        if {s["taskDefinition"] for s in latest} != {
            s["taskDefinition"] for s in services
        }:
            raise ValueError("Service definitions changed during review")
        tasks = ecs.list_tasks(cluster=out["ecs_cluster"])["taskArns"]
        if tasks:
            active = ecs.describe_tasks(cluster=out["ecs_cluster"], tasks=tasks)[
                "tasks"
            ]
            if any(t["taskDefinitionArn"] in remove_tasks for t in active):
                raise ValueError("A retirement target became active")
        receipt = ROOT / ".artifacts/product-cloud-cleanup.json"
        report.update(passed=False, retired_task_definitions=[], deleted_images=[])
        receipt.write_text(json.dumps(report, indent=2, default=str))
        for arn in remove_tasks:
            ecs.deregister_task_definition(taskDefinition=arn)
            report["retired_task_definitions"].append(arn)
            receipt.write_text(json.dumps(report, indent=2, default=str))
        for image in remove_images:
            result = ecr.batch_delete_image(
                repositoryName=image["repository"],
                imageIds=[{"imageDigest": image["digest"]}],
            )
            if result.get("failures"):
                raise RuntimeError("Image retirement failed; preserve partial evidence")
            report["deleted_images"].extend(result.get("imageIds", []))
            receipt.write_text(json.dumps(report, indent=2, default=str))
        report["passed"] = True
    path = (
        ROOT
        / ".artifacts"
        / (
            "product-cloud-cleanup.json"
            if args.apply
            else "product-cloud-cleanup-plan.json"
        )
    )
    path.write_text(json.dumps(report, indent=2, default=str))
    print(
        json.dumps(
            {
                "apply": args.apply,
                "retired_task_revisions": len(remove_tasks),
                "retired_image_digests": len(remove_images),
                "retained_image_digests": len(retained),
                "logical_compressed_bytes_removed": report[
                    "logical_compressed_bytes_removed"
                ],
            }
        )
    )


if __name__ == "__main__":
    main()
