"""Preview repository protections; apply only during an authorized rollout."""

import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--apply", action="store_true")
a = parser.parse_args()
configuration = json.loads(
    (ROOT / "docs/deployment/github-protections.json").read_text()
)
print(json.dumps(configuration, indent=2))
if a.apply:
    import httpx

    credential = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        text=True,
        capture_output=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        check=True,
    )
    fields = dict(
        line.split("=", 1) for line in credential.stdout.splitlines() if "=" in line
    )
    if not fields.get("password"):
        raise SystemExit("GitHub repository administration authentication is required")
    headers = {
        "Authorization": "Bearer " + fields["password"],
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    base = "https://api.github.com/repos/notnikhilreddy/RepoGuide"
    with httpx.Client(headers=headers, timeout=15) as client:
        for endpoint, body in [
            ("/branches/main/protection", configuration["protection"]),
            ("/environments/production", configuration["production_environment"]),
            ("/environments/quality", configuration["production_environment"]),
        ]:
            response = client.put(base + endpoint, json=body)
            if response.status_code not in {200, 201}:
                raise SystemExit(
                    "GitHub protection update failed: HTTP " + str(response.status_code)
                )
        result = client.get(base + "/branches/main/protection")
        if result.status_code != 200 or not result.json().get("enforce_admins", {}).get(
            "enabled"
        ):
            raise SystemExit("Protection verification failed")
    print("Repository protections applied and read back")
