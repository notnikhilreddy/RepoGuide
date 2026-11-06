"""Create/revoke only this release's private Vercel automation bypass.

API contract: https://vercel.com/docs/rest-api/projects/update-protection-bypass-for-automation
No secret is put in argv, environment variables, frontend assets or output.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import time

from product_vercel_inventory import ROOT, api


def private_json(path, value):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "revoke"])
    args = parser.parse_args()
    linked = json.loads((ROOT / ".vercel/project.json").read_text())
    project = api("/v9/projects/repo-guide")
    if project["id"] != linked["projectId"]:
        raise ValueError("Existing project identity changed")
    manifest = json.loads((ROOT / ".artifacts/release-manifest.json").read_text())
    path = ROOT / ".artifacts/private/vercel-smoke-bypass.json"
    if args.action == "create":
        from release_cloud import verify

        if verify()["status"] != "passed":
            raise ValueError("Passing release required before preview access")
        if path.exists():
            previous = json.loads(path.read_text())
            if previous["secret"] in project.get("protectionBypass", {}):
                raise ValueError("An active local bypass exists; revoke it first")
            path.rename(
                path.with_name("retired-bypass-" + str(time.time_ns()) + ".json")
            )
        value = {
            "secret": secrets.token_hex(32),
            "release_id": manifest["release_id"],
            "project_id": project["id"],
        }
        private_json(path, value)
        payload = {
            "generate": {
                "secret": value["secret"],
                "note": "RepoGuide product acceptance " + manifest["release_id"],
            }
        }
    else:
        value = json.loads(path.read_text())
        if value.get("project_id") != project["id"]:
            raise ValueError("Bypass does not belong to this project/release workflow")
        payload = {"revoke": {"secret": value["secret"], "regenerate": False}}
    body = path.with_name("bypass-request-" + str(time.time_ns()) + ".json")
    private_json(body, payload)
    result = subprocess.run(
        [
            "npx",
            "--yes",
            "vercel",
            "api",
            "/v1/projects/" + project["id"] + "/protection-bypass",
            "--scope",
            "white-walkers3",
            "--method",
            "PATCH",
            "--header",
            "Content-Type: application/json",
            "--input",
            str(body),
            "--raw",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if result.returncode:
        # The API error can echo the secret. Retain it only in a private file.
        private_json(
            body.with_suffix(".response.json"),
            {"stdout": result.stdout, "stderr": result.stderr},
        )
        raise RuntimeError("Preview access update failed; inspect private response")
    after = api("/v9/projects/repo-guide").get("protectionBypass", {})
    active = value["secret"] in after
    if active != (args.action == "create"):
        raise ValueError("Preview bypass read-back mismatch")
    if set(after) - {value["secret"]} != set(project.get("protectionBypass", {})) - {
        value["secret"]
    }:
        raise ValueError("Unrelated bypass entries changed; inspect concurrent changes")
    if args.action == "revoke":
        (ROOT / ".artifacts/vercel-bypass-cleanup.json").write_text(
            json.dumps(
                {
                    "temporary_bypass_revoked": True,
                    "release_id": value["release_id"],
                    "unrelated_bypasses_unchanged": True,
                }
            )
        )
    print(
        json.dumps(
            {"action": args.action, "verified": True, "release_id": value["release_id"]}
        )
    )


if __name__ == "__main__":
    main()
