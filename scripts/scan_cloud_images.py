"""Inventory and scan final local images without publishing or exposing secrets."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / ".artifacts"
PRIVATE = ARTIFACTS / "private"
PRIVATE.mkdir(parents=True, exist_ok=True)
PRIVATE.chmod(0o700)
host = subprocess.check_output(
    ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
    text=True,
).strip()
env = {**os.environ, "DOCKER_HOST": os.getenv("DOCKER_HOST", host)}
report = {"created_at": datetime.now(timezone.utc).isoformat(), "images": {}}
program = """import importlib.metadata,json,torch; print(json.dumps({'torch_version':str(torch.__version__),'cuda_version':torch.version.cuda,'packages':sorted((d.metadata['Name'].lower().replace('_','-'),d.version) for d in importlib.metadata.distributions())}))"""
for kind in ["answer", "index"]:
    image = "repoguide-" + kind + ":candidate"
    identity = subprocess.check_output(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"], text=True
    ).strip()
    inventory = json.loads(
        subprocess.check_output(
            [
                "docker",
                "run",
                "--rm",
                "--platform",
                "linux/amd64",
                "--read-only",
                "--tmpfs",
                "/tmp:rw,size=256m",
                image,
                "python",
                "-c",
                program,
            ],
            text=True,
        )
    )
    names = {name for name, _ in inventory["packages"]}
    forbidden = (
        {
            "mlflow",
            "tree-sitter",
            "tree-sitter-python",
            "tree-sitter-javascript",
            "tree-sitter-typescript",
        }
        if kind == "answer"
        else {"mlflow", "google-genai", "openai", "langgraph", "mcp"}
    )
    cpu_only = (
        inventory["cuda_version"] is None
        and inventory["torch_version"].endswith("+cpu")
        and not any(n.startswith("nvidia-") for n in names)
    )
    if not cpu_only or forbidden & names:
        raise SystemExit("Unexpected GPU or cross-role dependencies in " + kind)
    (ARTIFACTS / (kind + "-inventory.json")).write_text(json.dumps(inventory, indent=2))
    vulnerabilities = ARTIFACTS / (kind + "-vulnerabilities.json")
    subprocess.run(
        [
            "trivy",
            "image",
            "--image-src",
            "docker",
            "--scanners",
            "vuln",
            "--severity",
            "HIGH,CRITICAL",
            "--format",
            "json",
            "--output",
            str(vulnerabilities),
            image,
        ],
        env=env,
        check=True,
    )
    result = json.loads(vulnerabilities.read_text())
    rows = [v for r in result.get("Results", []) for v in r.get("Vulnerabilities", [])]
    secret_path = PRIVATE / (kind + "-image-secret-scan.json")
    subprocess.run(
        [
            "trivy",
            "image",
            "--image-src",
            "docker",
            "--scanners",
            "secret",
            "--image-config-scanners",
            "secret",
            "--format",
            "json",
            "--output",
            str(secret_path),
            image,
        ],
        env=env,
        check=True,
    )
    secret_path.chmod(0o600)
    secrets_result = json.loads(secret_path.read_text())
    secret_count = sum(
        len(r.get("Secrets", [])) for r in secrets_result.get("Results", [])
    )
    subprocess.run(
        [
            "trivy",
            "image",
            "--image-src",
            "docker",
            "--format",
            "cyclonedx",
            "--output",
            str(ARTIFACTS / (kind + "-sbom.cdx.json")),
            image,
        ],
        env=env,
        check=True,
    )
    after = subprocess.check_output(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"], text=True
    ).strip()
    if after != identity:
        raise SystemExit("Image changed during scanning")
    report["images"][kind] = {
        "image_id": identity,
        "cpu_only": cpu_only,
        "forbidden_dependencies": sorted(forbidden & names),
        "secret_findings": secret_count,
        "critical": sum(v["Severity"] == "CRITICAL" for v in rows),
        "high": sum(v["Severity"] == "HIGH" for v in rows),
        "fixable_high": sum(
            v["Severity"] == "HIGH" and bool(v.get("FixedVersion")) for v in rows
        ),
        "report_sha256": hashlib.sha256(vulnerabilities.read_bytes()).hexdigest(),
    }
(ARTIFACTS / "security-summary.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
if any(
    v["secret_findings"] or v["critical"] or v["fixable_high"]
    for v in report["images"].values()
):
    raise SystemExit(
        "Image security gate blocked; inspect private/redacted scan evidence"
    )
