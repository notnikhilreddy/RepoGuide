"""Read the existing Vercel project and deployments; preserve raw data privately."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def api(path):
    raw = subprocess.check_output(
        [
            "npx",
            "--yes",
            "vercel",
            "api",
            path,
            "--scope",
            "white-walkers3",
            "--raw",
        ],
        text=True,
        cwd=ROOT,
    )
    return json.loads(raw)


def main():
    private = ROOT / ".artifacts/private"
    private.mkdir(exist_ok=True, mode=0o700)
    projects = api("/v9/projects?limit=100")
    project = api("/v9/projects/repo-guide")
    deployments = api("/v6/deployments?projectId=" + project["id"] + "&limit=100")
    path = private / "product-vercel-inventory.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(
            {"projects": projects, "project": project, "deployments": deployments},
            stream,
            indent=2,
        )
    owned = [p for p in projects.get("projects", []) if p["name"] == "repo-guide"]
    result = {
        "read_only": True,
        "existing_project": project["id"],
        "project_name": project["name"],
        "root_directory": project.get("rootDirectory"),
        "matching_projects": len(owned),
        "git_auto_deploy": project.get("gitProviderOptions", {}),
        "deployments": [
            {
                k: d.get(k)
                for k in ["uid", "url", "created", "state", "target", "aliasAssigned"]
            }
            for d in deployments.get("deployments", [])
        ],
        "production_targets": {
            k: {a: b for a, b in v.items() if a in ["id", "url", "alias"]}
            for k, v in project.get("targets", {}).items()
        },
    }
    (ROOT / ".artifacts/product-vercel-inventory.json").write_text(
        json.dumps(result, indent=2)
    )
    print(
        json.dumps(
            {
                "matching_projects": len(owned),
                "deployment_count": len(result["deployments"]),
                "project_name": project["name"],
                "root_directory": project.get("rootDirectory"),
            }
        )
    )


if __name__ == "__main__":
    main()
