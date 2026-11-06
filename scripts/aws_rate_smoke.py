"""Verify real per-user conversation quota without jobs, models or worker starts."""

from __future__ import annotations

import json
import secrets
import subprocess
import time
import uuid
from pathlib import Path

import boto3
import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = {
        k: v["value"]
        for k, v in json.loads(
            subprocess.check_output(
                [
                    "terraform",
                    "-chdir=" + str(ROOT / "infra/terraform"),
                    "output",
                    "-json",
                ],
                text=True,
            )
        ).items()
    }
    cognito = boto3.Session(profile_name="repoguide", region_name="us-east-2").client(
        "cognito-idp"
    )
    name = "rate-smoke-" + uuid.uuid4().hex[:12] + "@example.invalid"
    password = secrets.token_urlsafe(28) + "Aa9!"
    ids = []
    report = {"live_aws": True, "model_calls": 0, "job_submissions": 0}
    client = None
    created = False
    try:
        cognito.admin_create_user(
            UserPoolId=out["user_pool_id"],
            Username=name,
            MessageAction="SUPPRESS",
            UserAttributes=[
                {"Name": "email", "Value": name},
                {"Name": "email_verified", "Value": "true"},
            ],
        )
        created = True
        cognito.admin_set_user_password(
            UserPoolId=out["user_pool_id"],
            Username=name,
            Password=password,
            Permanent=True,
        )
        token = cognito.admin_initiate_auth(
            UserPoolId=out["user_pool_id"],
            ClientId=out["cognito_client_id"],
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": name, "PASSWORD": password},
        )["AuthenticationResult"]["AccessToken"]
        client = httpx.Client(
            base_url=out["api_url"],
            headers={"Authorization": "Bearer " + token},
            timeout=20,
        )
        report["release_id"] = client.get("/health").json()["release"]
        if (
            report["release_id"]
            != json.loads((ROOT / ".artifacts/release-manifest.json").read_text())[
                "release_id"
            ]
        ):
            raise ValueError("Release mismatch")
        repos = client.get("/api/ui/repositories")
        repos.raise_for_status()
        repo_id = repos.json()[0]["id"]
        if int(time.time()) % 60 > 45:
            time.sleep(61 - int(time.time()) % 60)
        before = client.get("/api/compute/status").json()["workers"]
        responses = []
        for _ in range(6):
            response = client.post(
                "/api/conversations",
                json={"repo_id": repo_id, "title": "Temporary rate verification"},
            )
            responses.append(response)
            if response.status_code == 201:
                ids.append(response.json()["id"])
        report["status_codes"] = [r.status_code for r in responses]
        assert report["status_codes"] == [201] * 5 + [429]
        assert "minute" in responses[-1].json()["detail"]
        after = client.get("/api/compute/status").json()["workers"]
        assert all(
            before[k].get(f) == after[k].get(f)
            for k in ["answer", "index"]
            for f in ["desired_state", "idle_since", "pending", "worker_id"]
        )
        report.update(passed=True, worker_idle_fields_unchanged=True)
    finally:
        if client:
            for id in ids:
                response = client.delete("/api/conversations/" + id)
                response.raise_for_status()
            client.close()
        if created:
            cognito.admin_delete_user(UserPoolId=out["user_pool_id"], Username=name)
        report["temporary_conversations_removed"] = len(ids)
        report["temporary_user_removed"] = created
        (ROOT / ".artifacts/aws-rate-verification.json").write_text(
            json.dumps(report, indent=2)
        )
    print(json.dumps(report))


if __name__ == "__main__":
    main()
