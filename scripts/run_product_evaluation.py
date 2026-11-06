"""Run the measured deployed baseline or exact candidate with one $2 ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from update_runtime_settings import load_settings

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["baseline", "candidate"])
    args = parser.parse_args()
    output = ROOT / ".artifacts/product-eval"
    output.mkdir(exist_ok=True)
    baseline = ROOT / ".artifacts/improvement-baseline"
    descriptor = baseline / "identity.json"
    if args.phase == "baseline":
        image = (
            "sha256:c5ecb2b7ffe6668b2ab0c4fe69aace5266ffca8221ff2587e7e50862d3868ced"
        )
        config = json.loads((baseline / "release-config.json").read_text())
        source_hash = hashlib.sha256(
            b"".join(
                p.read_bytes()
                for p in sorted((baseline / "src/repoguide").glob("*.py"))
            )
        ).hexdigest()
        if source_hash != config["source_sha256"]:
            raise SystemExit(
                "Snapshot is not the exact starting release; baseline cannot be claimed"
            )
        identity = {
            "image": image,
            "source_sha256": source_hash,
            "release_config": config,
            "provenance": "Starting deployed release, measured without changing its source. Evaluation routing uses llm for both phases.",
        }
        if descriptor.exists() and json.loads(descriptor.read_text()) != identity:
            raise SystemExit("Protected starting baseline identity changed")
        descriptor.write_text(json.dumps(identity, indent=2))
    else:
        image = "repoguide-answer:candidate"
        config = json.loads((ROOT / "deployment/release-config.json").read_text())
    retrieval_cache = None
    previous_report = output / (args.phase + "-evaluation.json")
    if previous_report.exists():
        previous = json.loads(previous_report.read_text())
        if args.phase == "baseline" and previous.get("complete"):
            raise SystemExit(
                "A complete starting baseline is already protected; do not overwrite it"
            )
        import time

        archived = output / (args.phase + "-attempt-" + str(time.time_ns()) + ".json")
        previous_report.rename(archived)
        if previous.get("source_sha256") == config["source_sha256"] and set(
            previous.get("retrieval_modes", {})
        ) == {
            "dense",
            "keyword",
            "graph",
            "hybrid",
            "hybrid_rerank",
            "hybrid_graph",
            "hybrid_graph_rerank",
        }:
            retrieval_cache = "/evidence/" + archived.name
    image_id = subprocess.check_output(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"], text=True
    ).strip()
    secrets = load_settings(ROOT / ".env.deploy")
    env = {
        **os.environ,
        **{
            k: v
            for k, v in secrets.items()
            if k in ["OPENAI_API_KEY", "CONTEXT7_API_KEY"]
        },
        **config["runtime"],
        "DATABASE_URL": "postgresql+psycopg://repoguide:repoguide@host.docker.internal:55432/repoguide?sslmode=require&connect_timeout=5",
        "ROUTER_PROVIDER": "llm",
        "REPOGUIDE_EVALUATION": "true",
        "MLFLOW_ENABLED": "false",
        "REPOGUIDE_CLOUD_MODE": "true",
        "EVALUATED_IMAGE_ID": image_id,
        "REPOGUIDE_EVALUATION_HARDWARE": "linux/amd64;1vCPU;4GiB;host="
        + os.uname().sysname,
        "REPOGUIDE_EVAL_BUDGET_FILE": "/evidence/spend.json",
    }
    command = [
        "docker",
        "run",
        "--rm",
        "--label",
        "repoguide.product-evaluation",
        "--platform",
        "linux/amd64",
        "--cpus",
        "1",
        "--memory",
        "4g",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,size=1g",
        "-v",
        str(ROOT / "evals") + ":/evals:ro",
        "-v",
        str(ROOT / "deployment") + ":/deployment:ro",
        "-v",
        str(output) + ":/evidence",
    ]
    if args.phase == "baseline":
        command += [
            "-v",
            str(baseline / "src") + ":/baseline/src:ro",
            "--env",
            "PYTHONPATH=/baseline/src",
        ]
    for key in sorted(
        set(config["runtime"])
        | {
            "OPENAI_API_KEY",
            "CONTEXT7_API_KEY",
            "DATABASE_URL",
            "REPOGUIDE_EVALUATION",
            "MLFLOW_ENABLED",
            "REPOGUIDE_CLOUD_MODE",
            "EVALUATED_IMAGE_ID",
            "REPOGUIDE_EVALUATION_HARDWARE",
            "REPOGUIDE_EVAL_BUDGET_FILE",
        }
    ):
        if key in env:
            command += ["--env", key]
    command += [
        image,
        "python",
        "/evals/release_eval.py",
        "--output",
        "/evidence/" + args.phase + "-evaluation.json",
    ]
    if retrieval_cache:
        command += ["--retrieval-cache", retrieval_cache]
    raise SystemExit(subprocess.run(command, env=env).returncode)


if __name__ == "__main__":
    main()
