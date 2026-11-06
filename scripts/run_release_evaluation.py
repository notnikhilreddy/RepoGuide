"""Run a cost-bounded evaluator using a secret-safe container environment."""

import argparse
import json
import os
import platform
import subprocess
from pathlib import Path

from update_runtime_settings import load_settings

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("phase", choices=["baseline", "candidate"])
parser.add_argument("--baseline-manifest")
a = parser.parse_args()
if (root / ".artifacts/live-evaluation-paused").exists():
    raise SystemExit(
        "Live evaluation paused after an earlier failure; inspect its report before retrying"
    )
settings = (
    load_settings(root / ".env.deploy")
    if (root / ".env.deploy").exists()
    else {
        k: os.getenv(k, "")
        for k in ["OPENAI_API_KEY", "GEMINI_API_KEY", "JEV_API_KEY", "CONTEXT7_API_KEY"]
    }
)
runtime = json.loads((root / "deployment/release-config.json").read_text())["runtime"]
image = "repoguide-answer:candidate"
if a.phase == "baseline" and a.baseline_manifest:
    approved = json.loads(Path(a.baseline_manifest).read_text())
    image = approved["images"]["answer"]
    runtime = approved["runtime"]
    subprocess.run(["docker", "pull", image], check=True)
output_path = root / ".artifacts" / (a.phase + "-evaluation.json")
if output_path.exists():
    raise SystemExit(
        "Preserve existing evaluation evidence; archive incomplete attempts explicitly before rerunning"
    )
identity = subprocess.check_output(
    ["docker", "image", "inspect", image, "--format", "{{.Id}}"], text=True
).strip()
env = {
    **os.environ,
    **{
        k: v
        for k, v in settings.items()
        if k in ["OPENAI_API_KEY", "GEMINI_API_KEY", "JEV_API_KEY", "CONTEXT7_API_KEY"]
    },
    **runtime,
    "DATABASE_URL": "postgresql+psycopg://repoguide:repoguide@host.docker.internal:55432/repoguide?sslmode=require&connect_timeout=5",
    "REPOGUIDE_EVALUATION": "true",
    "REPOGUIDE_CLOUD_MODE": "true",
    "MLFLOW_ENABLED": "false",
    "EVALUATED_IMAGE_ID": identity,
    "REPOGUIDE_EVAL_BUDGET_FILE": "/evidence/evaluation-spend.json",
    "REPOGUIDE_EVALUATION_HARDWARE": "linux/amd64;1vCPU;4GiB;host="
    + platform.system()
    + "/"
    + platform.machine(),
}
args = [
    "docker",
    "run",
    "--rm",
    "--platform",
    "linux/amd64",
    "--cpus",
    "1",
    "--memory",
    "4g",
    "--read-only",
    "--tmpfs",
    "/tmp:rw,size=1g",
    "-v",
    str(root / "evals") + ":/evals:ro",
    "-v",
    str(root / "deployment") + ":/deployment:ro",
    "-v",
    str(root / ".artifacts") + ":/evidence",
]
if platform.system() == "Linux":
    args += ["--network", "host", "--add-host", "host.docker.internal:127.0.0.1"]
for key in set(runtime) | {
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "JEV_API_KEY",
    "CONTEXT7_API_KEY",
    "DATABASE_URL",
    "REPOGUIDE_EVALUATION",
    "REPOGUIDE_CLOUD_MODE",
    "MLFLOW_ENABLED",
    "EVALUATED_IMAGE_ID",
    "REPOGUIDE_EVAL_BUDGET_FILE",
    "REPOGUIDE_EVALUATION_HARDWARE",
}:
    if key in env:
        args += ["--env", key]
if a.phase == "baseline":
    args += [
        "-v",
        "/tmp/repoguide-baseline:/baseline:ro",
        "--env",
        "PYTHONPATH=/baseline/src",
    ]
args += [
    image,
    "python",
    "/evals/release_eval.py",
    "--output",
    "/evidence/" + a.phase + "-evaluation.json",
]
result = subprocess.run(args, env=env)
if result.returncode:
    (root / ".artifacts/live-evaluation-paused").write_text(
        "Evaluation failed during "
        + a.phase
        + ". Inspect the saved partial report before deliberately retrying.\n"
    )
raise SystemExit(result.returncode)
