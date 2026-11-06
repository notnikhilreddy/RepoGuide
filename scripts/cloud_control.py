"""Explicit IAM-authenticated operator controls for independent worker services.

This CLI uses the same durable state machine as the administrator UI. It never
uses the retired control#worker/paused fields or scales up from queue traffic.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "start", "stop"])
    parser.add_argument("kind", choices=["answer", "index"])
    parser.add_argument("--profile", default=os.getenv("AWS_PROFILE", "repoguide"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    outputs = json.loads(
        subprocess.check_output(
            ["terraform", "-chdir=infra/terraform", "output", "-json"], text=True
        )
    )
    if not all(
        key in outputs for key in ["ecs_cluster", "ecs_services", "queues", "job_table"]
    ):
        parser.error("New deployment outputs are absent; no control action was taken")
    os.environ["AWS_PROFILE"] = args.profile
    os.environ["AWS_DEFAULT_REGION"] = "us-east-2"
    for name, key in [
        ("REPOGUIDE_ECS_CLUSTER", "ecs_cluster"),
        ("REPOGUIDE_JOB_TABLE", "job_table"),
    ]:
        os.environ[name] = outputs[key]["value"]
    for kind in ["answer", "index"]:
        os.environ["REPOGUIDE_" + kind.upper() + "_SERVICE"] = outputs["ecs_services"][
            "value"
        ][kind]
        os.environ["REPOGUIDE_" + kind.upper() + "_QUEUE_URL"] = outputs["queues"][
            "value"
        ][kind]
    from repoguide import cloud_state as state

    state.clients.cache_clear()
    if args.action == "status":
        result = state.status(args.kind)
    else:
        import boto3

        identity = boto3.client("sts").get_caller_identity()["Arn"]
        result = (
            state.start_service(args.kind, identity)
            if args.action == "start"
            else state.stop_service(args.kind, identity, args.force)
        )
    print(json.dumps(result, default=str, indent=2))


if __name__ == "__main__":
    main()
