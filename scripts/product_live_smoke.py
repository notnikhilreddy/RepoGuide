"""Real signed-token product checks using only uniquely created test accounts/chats.

No worker starts, paid model calls, fabricated results, or existing data changes.
"""

from __future__ import annotations

import argparse
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registration-enabled", action="store_true")
    args = parser.parse_args()
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
    session = boto3.Session(profile_name="repoguide", region_name="us-east-2")
    cognito = session.client("cognito-idp")
    http = httpx.Client(base_url=out["api_url"], timeout=20)
    users = []
    chats = []
    report = {
        "live_aws": True,
        "live_cognito": True,
        "started_workers": False,
        "model_calls": 0,
        "checks": {},
        "created_at": int(time.time()),
    }

    def request(token, method, path, body=None, expected=200):
        response = http.request(
            method,
            path,
            json=body,
            headers={"Authorization": "Bearer " + token} if token else {},
        )
        if response.status_code != expected:
            raise AssertionError(
                f"{method} {path}: HTTP {response.status_code}, expected {expected}"
            )
        return response.json()

    try:
        report["release_id"] = request(None, "GET", "/health")["release"]
        expected = json.loads((ROOT / ".artifacts/release-manifest.json").read_text())[
            "release_id"
        ]
        if report["release_id"] != expected:
            raise ValueError("Release identity mismatch")
        request(None, "GET", "/api/conversations", expected=401)
        for _ in range(2):
            username = "product-smoke-" + uuid.uuid4().hex[:14] + "@example.invalid"
            password = secrets.token_urlsafe(24) + "Aa9!"
            cognito.admin_create_user(
                UserPoolId=out["user_pool_id"],
                Username=username,
                MessageAction="SUPPRESS",
                UserAttributes=[
                    {"Name": "email", "Value": username},
                    {"Name": "email_verified", "Value": "true"},
                ],
            )
            users.append(username)
            cognito.admin_set_user_password(
                UserPoolId=out["user_pool_id"],
                Username=username,
                Password=password,
                Permanent=True,
            )
            auth = cognito.admin_initiate_auth(
                UserPoolId=out["user_pool_id"],
                ClientId=out["cognito_client_id"],
                AuthFlow="ADMIN_USER_PASSWORD_AUTH",
                AuthParameters={"USERNAME": username, "PASSWORD": password},
            )["AuthenticationResult"]
            token = auth["AccessToken"]
            if len(users) == 1:
                first_token = token
                first_auth = auth
            else:
                second_token = token
        repos = request(first_token, "GET", "/api/ui/repositories")
        if not repos or any(r.get("visibility") != "shared" for r in repos):
            raise ValueError("Unexpected initial demo catalog")
        repo = repos[0]
        for token in [first_token, second_token]:
            request(token, "POST", "/api/compute/answer/start", {}, expected=403)
            request(token, "POST", "/api/compute/index/stop", {}, expected=403)
        before = request(first_token, "GET", "/api/compute/status")
        document = request(
            first_token,
            "POST",
            "/api/conversations",
            {"repo_id": repo["id"], "title": "Product smoke — safe to remove"},
            expected=201,
        )
        chats.append((first_token, document["id"]))
        url = "/api/conversations/" + document["id"]
        request(second_token, "GET", url, expected=404)
        request(second_token, "PATCH", url, {"title": "forbidden"}, expected=404)
        request(second_token, "DELETE", url, expected=404)
        assert not request(second_token, "GET", "/api/conversations")
        request(first_token, "PATCH", url, {"title": "Saved across sessions"})
        renewed = cognito.initiate_auth(
            ClientId=out["cognito_client_id"],
            AuthFlow="REFRESH_TOKEN_AUTH",
            AuthParameters={"REFRESH_TOKEN": first_auth["RefreshToken"]},
        )["AuthenticationResult"]["AccessToken"]
        assert request(renewed, "GET", url)["title"] == "Saved across sessions"
        page = request(renewed, "GET", "/api/conversations?page=1&q=Saved")
        assert document["id"] in {x["id"] for x in page["items"]}
        architecture = request(
            first_token, "GET", "/repositories/" + repo["id"] + "/architecture"
        )
        assert architecture["nodes"] and len(architecture["nodes"]) <= 60
        request(first_token, "GET", "/repositories/" + repo["id"] + "/health")
        request(first_token, "GET", "/api/usage")
        request(first_token, "GET", "/api/jobs")
        pool = cognito.describe_user_pool(UserPoolId=out["user_pool_id"])["UserPool"]
        assert (
            pool["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"]
            is not args.registration_enabled
        )
        report["public_registration_enabled"] = not pool["AdminCreateUserConfig"][
            "AllowAdminCreateUserOnly"
        ]
        if before["workers"]["answer"]["desired_state"] == "off":
            request(
                first_token,
                "POST",
                url + "/messages",
                {
                    "message_id": str(uuid.uuid4()),
                    "question": "Keep this question when workers are offline.",
                },
                expected=409,
            )
            saved = request(renewed, "GET", url)
            assert (
                saved["messages"][0]["content"]
                == "Keep this question when workers are offline."
            )
            assert saved["messages"][-1]["status"] == "failed"
            report["checks"]["offline_prompt_durable"] = True
        after = request(first_token, "GET", "/api/compute/status")
        assert {k: v["desired_state"] for k, v in before["workers"].items()} == {
            k: v["desired_state"] for k, v in after["workers"].items()
        }
        report["checks"].update(
            anonymous_denied=True,
            owner_isolation=True,
            second_session_refresh=True,
            history_search=True,
            architecture_bounded=True,
            admin_controls_denied=True,
            no_surprise_compute=True,
            registration_flag=True,
        )
        for token, conversation_id in chats:
            request(token, "DELETE", "/api/conversations/" + conversation_id)
            request(token, "GET", "/api/conversations/" + conversation_id, expected=404)
        chats.clear()
        report["passed"] = True
    finally:
        for token, conversation_id in chats:
            try:
                request(token, "DELETE", "/api/conversations/" + conversation_id)
            except Exception:
                pass
        for username in users:
            cognito.admin_delete_user(UserPoolId=out["user_pool_id"], Username=username)
        report["temporary_users_removed"] = len(users)
        (ROOT / ".artifacts/product-live-api-smoke.json").write_text(
            json.dumps(report, indent=2)
        )
        http.close()
    print(json.dumps(report))


if __name__ == "__main__":
    main()
