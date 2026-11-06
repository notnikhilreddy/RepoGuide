"""Prepare a secret-free exact frontend snapshot; optionally deploy without cutover.

Uses the existing Vercel project, production public environment and --skip-domain.
The isolated directory avoids sending repository secrets or Git-scope metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from product_vercel_inventory import api
from release_cloud import ROOT, release_fingerprint, verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deploy", action="store_true")
    args = parser.parse_args()
    if args.deploy and verify()["status"] != "passed":
        raise ValueError("A passing measured release is required")
    linked = json.loads((ROOT / ".vercel/project.json").read_text())
    project = api("/v9/projects/repo-guide") if args.deploy else None
    if project and (
        project["id"] != linked["projectId"]
        or project.get("rootDirectory") != "frontend"
    ):
        raise ValueError("Existing project identity/root changed")
    directory = Path(
        tempfile.mkdtemp(prefix="repoguide-product-preview-", dir="/private/tmp")
    )
    files = (
        subprocess.check_output(["git", "ls-files", "-z", "frontend"], cwd=ROOT)
        .decode()
        .split("\0")
    )
    proof = []
    for name in files:
        if not name:
            continue
        source = ROOT / name
        target = directory / name
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError("Snapshot bytes differ")
            proof.append({"path": name, "sha256": digest})
    (directory / ".vercel").mkdir()
    (directory / ".vercel/project.json").write_text(json.dumps(linked))
    (directory / ".vercelignore").write_text(
        ".git\n.env*\nfrontend/.env*\n!frontend/.env.production.example\n"
    )
    report = {
        "passed": True,
        "snapshot": str(directory),
        "release_fingerprint": release_fingerprint(),
        "files": proof,
        "source": "Every tracked frontend file, byte-for-byte; no credentials, local databases, node_modules or build artifacts.",
    }
    (ROOT / ".artifacts/vercel-source-equivalence.json").write_text(
        json.dumps(report, indent=2)
    )
    if not args.deploy:
        print(
            json.dumps(
                {"prepared": True, "files": len(proof), "snapshot": str(directory)}
            )
        )
        return
    result = subprocess.run(
        [
            "npx",
            "--yes",
            "vercel",
            "deploy",
            "--cwd",
            str(directory),
            "--prod",
            "--skip-domain",
            "--yes",
            "--scope",
            "white-walkers3",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=900,
    )
    log = ROOT / ".artifacts/private/product-vercel-deploy.log"
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(result.stdout + "\n" + result.stderr)
    if result.returncode:
        raise RuntimeError("Vercel deployment failed; inspect the private log")
    matches = re.findall(r"https://[a-z0-9-]+\.vercel\.app", result.stdout)
    if not matches:
        raise ValueError("No deployment URL returned")
    url = matches[-1]
    details = api("/v13/deployments/" + url.removeprefix("https://"))
    if (
        details.get("projectId") != linked["projectId"]
        or details.get("readyState") != "READY"
    ):
        raise ValueError("Deployment project/state mismatch")
    preview = {
        "project": "repo-guide",
        "url": url,
        "deployment_id": details["id"],
        "production_domain_promoted": False,
        "release_fingerprint": release_fingerprint(),
    }
    (ROOT / ".artifacts/vercel-preview.json").write_text(json.dumps(preview, indent=2))
    print(json.dumps(preview))


if __name__ == "__main__":
    main()
