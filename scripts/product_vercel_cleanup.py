"""Retire only unaliased deployments in the existing verified Vercel project."""

from __future__ import annotations

import argparse
import json
import subprocess
import time

from product_vercel_inventory import api
from release_cloud import ROOT, verify


def active_alias_deployments(project_id):
    path = "/v4/aliases?projectId=" + project_id + "&limit=100"
    result = set()
    while path:
        page = api(path)
        for alias in page.get("aliases", []):
            deployment = alias.get("deployment")
            id = (
                deployment.get("id")
                if isinstance(deployment, dict)
                else alias.get("deploymentId")
            )
            if not id:
                raise ValueError(
                    "Unknown alias ownership; preserve deployments for review"
                )
            result.add(id)
        cursor = page.get("pagination", {}).get("next")
        path = (
            "/v4/aliases?projectId=" + project_id + "&limit=100&until=" + str(cursor)
            if cursor
            else None
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((ROOT / ".artifacts/release-manifest.json").read_text())
    cutover = json.loads((ROOT / ".artifacts/vercel-cutover.json").read_text())
    before = json.loads(
        (ROOT / ".artifacts/improvement-baseline/vercel-inventory.json").read_text()
    )
    browser = json.loads(
        (ROOT / ".artifacts/browser-production-smoke.json").read_text()
    )
    if (
        not cutover.get("passed")
        or cutover["backend_release_id"] != manifest["release_id"]
        or not browser.get("passed")
        or browser["release_id"] != manifest["release_id"]
    ):
        raise ValueError("Verified current production cutover required")
    project = api("/v9/projects/repo-guide")
    if (
        project["id"] != before["existing_project"]
        or project.get("rootDirectory") != "frontend"
    ):
        raise ValueError("Project identity mismatch")
    if (
        project.get("targets", {}).get("production", {}).get("id")
        != cutover["deployment_id"]
    ):
        raise ValueError("Production target changed")
    protected = (
        {cutover["deployment_id"]}
        | {v["id"] for v in before["production_targets"].values()}
        | {v["id"] for v in project.get("targets", {}).values()}
        | active_alias_deployments(project["id"])
    )
    rows = []
    path = "/v6/deployments?projectId=" + project["id"] + "&limit=100"
    while path:
        page = api(path)
        rows.extend(page.get("deployments", []))
        cursor = page.get("pagination", {}).get("next")
        path = (
            "/v6/deployments?projectId="
            + project["id"]
            + "&limit=100&until="
            + str(cursor)
            if cursor
            else None
        )
    candidates = []
    for row in rows:
        if row["uid"] in protected:
            continue
        details = api("/v13/deployments/" + row["uid"])
        if details.get("projectId") != project["id"]:
            raise ValueError("Deployment belongs to another project")
        if details.get("readyState") not in {"READY", "ERROR", "CANCELED"}:
            continue
        candidates.append(
            {"id": row["uid"], "url": row["url"], "state": details.get("readyState")}
        )
    report = {
        "release_id": manifest["release_id"],
        "apply": args.apply,
        "observed_at": int(time.time()),
        "project_id": project["id"],
        "protected_deployments": sorted(protected),
        "candidates": candidates,
        "deleted": [],
        "cost_note": "Retires stale build/deployment artifacts; no always-on Vercel runtime savings are claimed.",
    }
    if args.apply:
        if verify()["status"] != "passed":
            raise ValueError("Passing measured release required")
        for row in candidates:
            current = api("/v9/projects/repo-guide")
            if row["id"] in {
                x["id"] for x in current.get("targets", {}).values()
            } | active_alias_deployments(project["id"]):
                raise ValueError(
                    "A retirement target gained an active alias; preserve it"
                )
            result = subprocess.run(
                [
                    "npx",
                    "--yes",
                    "vercel",
                    "api",
                    "/v13/deployments/" + row["id"],
                    "--scope",
                    "white-walkers3",
                    "--method",
                    "DELETE",
                    "--dangerously-skip-permissions",
                    "--silent",
                ],
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            if result.returncode:
                raise RuntimeError("Deployment retirement failed")
            report["deleted"].append(row["id"])
            (ROOT / ".artifacts/product-vercel-cleanup.json").write_text(
                json.dumps(report, indent=2)
            )
        report["passed"] = True
    path = (
        ROOT
        / ".artifacts"
        / (
            "product-vercel-cleanup.json"
            if args.apply
            else "product-vercel-cleanup-plan.json"
        )
    )
    path.write_text(json.dumps(report, indent=2))
    print(
        json.dumps(
            {
                "apply": args.apply,
                "candidates": len(candidates),
                "deleted": len(report["deleted"]),
                "retained": len(protected),
            }
        )
    )


if __name__ == "__main__":
    main()
