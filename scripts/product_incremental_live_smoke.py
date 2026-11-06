"""Index a previous public commit, then verify explicit incremental update in production.

Uses a unique temporary ordinary user and real upstream history. Does not publish
commits or change upstream branches. Only this identity's test indexes are removed.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import subprocess
import tempfile
import time
import uuid

import boto3
import httpx
import psycopg
from product_database_rollout import ROOT, database_url, readonly, snapshot


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
    session = boto3.Session(profile_name="repoguide", region_name="us-east-2")
    cognito = session.client("cognito-idp")
    username = "product-update-" + uuid.uuid4().hex[:12] + "@example.invalid"
    password = secrets.token_urlsafe(24) + "Aa9!"
    private = ROOT / ".artifacts/private/cognito-incremental-smoke.json"
    if private.exists():
        raise ValueError(
            "Preserve the existing smoke credential file for recovery before another run"
        )
    created = private_written = False
    cleanup_safe = True
    jobs = []
    client = None
    subject = None
    old_id = None
    report = {
        "live_aws": True,
        "live_github": True,
        "upstream_mutations": False,
        "model_generation_calls": 0,
        "checks": {},
    }

    def request(method, path, body=None, expected=200):
        response = client.request(
            method, path, json=body, headers={"Idempotency-Key": str(uuid.uuid4())}
        )
        if response.status_code != expected:
            raise AssertionError(
                f"{method} {path}: HTTP {response.status_code}, expected {expected}"
            )
        return response.json()

    def wait_job(id):
        started = time.monotonic()
        while time.monotonic() - started < 1000:
            job = request("GET", "/api/ui/jobs/" + id)
            if job["status"] == "complete":
                return job
            if job["status"] in {"failed", "cancelled"}:
                raise AssertionError("Index job ended " + job["status"])
            time.sleep(2)
        raise TimeoutError("Incremental index timeout")

    try:
        # A shallow clone supplies a real parent SHA without modifying upstream.
        with tempfile.TemporaryDirectory(
            prefix="repoguide-upstream-check-"
        ) as directory:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth=2",
                    "--filter=blob:none",
                    "--no-checkout",
                    "--single-branch",
                    "--branch",
                    "main",
                    "https://github.com/pallets/markupsafe",
                    directory,
                ],
                check=True,
                capture_output=True,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
                timeout=120,
            )
            old_sha = subprocess.check_output(
                ["git", "-C", directory, "rev-parse", "HEAD^"], text=True
            ).strip()
            head_sha = subprocess.check_output(
                ["git", "-C", directory, "rev-parse", "HEAD"], text=True
            ).strip()
        cognito.admin_create_user(
            UserPoolId=out["user_pool_id"],
            Username=username,
            MessageAction="SUPPRESS",
            UserAttributes=[
                {"Name": "email", "Value": username},
                {"Name": "email_verified", "Value": "true"},
            ],
        )
        created = True
        cognito.admin_set_user_password(
            UserPoolId=out["user_pool_id"],
            Username=username,
            Password=password,
            Permanent=True,
        )
        token = cognito.admin_initiate_auth(
            UserPoolId=out["user_pool_id"],
            ClientId=out["cognito_client_id"],
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": username, "PASSWORD": password},
        )["AuthenticationResult"]["AccessToken"]
        subject = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))[
            "sub"
        ]
        client = httpx.Client(
            base_url=out["api_url"],
            headers={"Authorization": "Bearer " + token},
            timeout=20,
        )
        report["release_id"] = request("GET", "/health")["release"]
        if (
            report["release_id"]
            != json.loads((ROOT / ".artifacts/release-manifest.json").read_text())[
                "release_id"
            ]
        ):
            raise ValueError("Release mismatch")
        if (
            request("GET", "/api/compute/status")["workers"]["index"]["desired_state"]
            != "on"
        ):
            raise ValueError(
                "An administrator must explicitly enable Index before this test"
            )
        job = request(
            "POST",
            "/api/ui/index-jobs",
            {
                "url": "https://github.com/pallets/markupsafe",
                "branch": "main",
                "commit_sha": old_sha,
            },
            expected=202,
        )
        jobs.append(job["id"])
        old = wait_job(job["id"])
        old_id = old["result"]["repo_id"]
        with readonly(database_url()) as db:
            old_rows = snapshot(db, [old_id])
        setup = {
            "username": username,
            "password": password,
            "api_url": out["api_url"],
            "old_repo_id": old_id,
            "old_sha": old_sha,
        }
        fd = os.open(private, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(setup, stream)
        private_written = True
        browser = subprocess.run(
            ["node", "scripts/browser_incremental_smoke.mjs"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=1100,
        )
        if browser.returncode:
            raise AssertionError(
                "Real incremental browser check failed; inspect its sanitized report"
            )
        measured = json.loads(
            (ROOT / ".artifacts/product-incremental-browser.json").read_text()
        )
        jobs.append(measured["job_id"])
        updated = wait_job(measured["job_id"])
        new_id = updated["result"]["repo_id"]
        if new_id == old_id:
            raise AssertionError("Update overwrote the old revision")
        health = request("GET", "/repositories/" + new_id + "/health")
        if (
            health["commit_sha"] != measured["remote_sha"]
            or not health.get("incremental")
            or health.get("reused_chunks", 0) <= 0
        ):
            raise AssertionError("Incremental revision/reuse evidence missing")
        duplicate = request(
            "POST", "/repositories/" + old_id + "/update", {}, expected=202
        )
        if duplicate["id"] != updated["id"]:
            raise AssertionError("Duplicate update created a second job")
        with readonly(database_url()) as db:
            if snapshot(db, [old_id]) != old_rows:
                raise AssertionError("Old revision changed")
        admin = json.loads((ROOT / ".artifacts/private/cognito-admin.json").read_text())
        other = cognito.admin_initiate_auth(
            UserPoolId=out["user_pool_id"],
            ClientId=out["cognito_client_id"],
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": admin["username"],
                "PASSWORD": admin["password"],
            },
        )["AuthenticationResult"]["AccessToken"]
        denied = httpx.get(
            out["api_url"] + "/api/ui/repositories/" + new_id + "/overview",
            headers={"Authorization": "Bearer " + other},
            timeout=20,
        )
        if denied.status_code != 404:
            raise AssertionError("Private test index leaked to another identity")
        report.update(
            passed=True,
            old_sha=old_sha,
            observed_head_at_start=head_sha,
            target_sha=health["commit_sha"],
            reused_chunks=health["reused_chunks"],
            embedded_chunks=health["embedded_chunks"],
            changed_files={
                k: health.get(k)
                for k in ["added_files", "modified_files", "deleted_files"]
            },
        )
        report["checks"].update(
            real_update_badge=True,
            explicit_browser_update=True,
            old_revision_preserved=True,
            duplicate_idempotent=True,
            private_owner_isolation=True,
        )
    finally:
        if client:
            browser_report = ROOT / ".artifacts/product-incremental-browser.json"
            if old_id and browser_report.exists():
                recent = json.loads(browser_report.read_text())
                if recent.get("old_repo_id") == old_id and recent.get("job_id"):
                    jobs.append(recent["job_id"])
            try:
                jobs.extend(row["id"] for row in request("GET", "/api/jobs"))
            except Exception:
                cleanup_safe = False
            for id in dict.fromkeys(jobs):
                try:
                    job = request("GET", "/api/ui/jobs/" + id)
                    if job["status"] not in {"complete", "failed", "cancelled"}:
                        request("POST", "/api/ui/jobs/" + id + "/cancel", {})
                        deadline = time.monotonic() + 180
                        while time.monotonic() < deadline:
                            if request("GET", "/api/ui/jobs/" + id)["status"] in {
                                "complete",
                                "failed",
                                "cancelled",
                            }:
                                break
                            time.sleep(2)
                        else:
                            cleanup_safe = False
                except Exception:
                    cleanup_safe = False
            client.close()
        report["cleanup_deferred_for_active_or_unknown_jobs"] = not cleanup_safe
        if not cleanup_safe:
            report["passed"] = False
        if subject and cleanup_safe:
            before = json.loads(
                (ROOT / ".artifacts/product-database-backup.json").read_text()
            )["snapshot"]["repository_ids"]
            with psycopg.connect(database_url(), connect_timeout=10) as db:
                ids = [
                    r[0]
                    for r in db.execute(
                        "SELECT id FROM repositories WHERE owner_sub=%s AND url=%s",
                        (subject, "https://github.com/pallets/markupsafe"),
                    )
                ]
                if any(id in before for id in ids):
                    raise ValueError(
                        "Cleanup attempted to touch an original repository"
                    )
                for id in ids:
                    db.execute(
                        "DELETE FROM repositories WHERE id=%s AND owner_sub=%s",
                        (id, subject),
                    )
            for id in ids:
                session.client("dynamodb").delete_item(
                    TableName=out["job_table"],
                    Key={"pk": {"S": "repository#" + id}},
                    ConditionExpression="owner_sub=:s",
                    ExpressionAttributeValues={":s": {"S": subject}},
                )
            report["temporary_indexes_removed"] = len(ids)
        if created and cleanup_safe:
            cognito.admin_delete_user(UserPoolId=out["user_pool_id"], Username=username)
        if private_written and cleanup_safe:
            private.unlink(missing_ok=True)
        (ROOT / ".artifacts/product-incremental-live-smoke.json").write_text(
            json.dumps(report, indent=2)
        )
    print(json.dumps(report))
    if not report.get("passed"):
        raise RuntimeError("Smoke verification or cleanup is incomplete")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"passed": False, "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
