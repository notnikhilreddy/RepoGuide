"""Configure the existing Vercel project from new Terraform outputs after gating.

Default is preview-only and does not contact Vercel. --apply verifies the release
and updates only public VITE settings. It never creates a project or promotes.
"""

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--apply", action="store_true")
a = parser.parse_args()
outputs = json.loads(
    subprocess.check_output(
        ["terraform", "-chdir=" + str(ROOT / "infra/terraform"), "output", "-json"],
        text=True,
    )
)
keys = {
    "VITE_API_BASE_URL": "api_url",
    "VITE_COGNITO_ISSUER": "cognito_issuer",
    "VITE_COGNITO_CLIENT_ID": "cognito_client_id",
}
if not all(k in outputs and outputs[k].get("value") for k in keys.values()):
    raise SystemExit("New Terraform outputs are absent; Vercel is unchanged")
settings = [
    {
        "key": key,
        "value": outputs[name]["value"],
        "type": "plain",
        "target": ["production"],
    }
    for key, name in keys.items()
]
print(
    json.dumps(
        {
            "project": "repo-guide",
            "origin": "https://repo-guide-five.vercel.app",
            "variables": [v["key"] for v in settings],
            "apply": a.apply,
        },
        indent=2,
    )
)
if a.apply:
    from release_cloud import verify

    verify()
    for setting in settings:
        target = ROOT / (".artifacts/vercel-" + setting["key"] + ".json")
        target.write_text(json.dumps(setting))
        subprocess.run(
            [
                "npx",
                "--yes",
                "vercel",
                "api",
                "/v10/projects/repo-guide/env?upsert=true",
                "--scope",
                "white-walkers3",
                "--method",
                "POST",
                "--header",
                "Content-Type: application/json",
                "--input",
                str(target),
                "--silent",
            ],
            check=True,
        )
    env = "\n".join(v["key"] + "=" + v["value"] for v in settings) + "\n"
    (ROOT / "frontend/.env.production").write_text(env)
    print(
        "Existing project public settings updated. Build a gated preview before promotion."
    )
