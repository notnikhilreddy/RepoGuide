"""Public GitHub metadata, pinned revisions and rate-conscious freshness.

No user credentials or app installation tokens are needed. Private repositories
are rejected explicitly; an unavailable check is never reported as up to date.
"""

from __future__ import annotations

import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from repoguide import cloud_state as state


class GitHubError(RuntimeError):
    def __init__(self, status, retry_at=None):
        self.status, self.retry_at = status, retry_at
        super().__init__("GitHub access unavailable")


def request(path, *, etag=None):
    if os.getenv("REPOGUIDE_JOB_TABLE"):
        now = int(time.time())
        try:
            state.update(
                f"github-rate#{now // 3600}",
                "SET requests=if_not_exists(requests,:zero)+:one, expires_at=:ttl",
                {":zero": 0, ":one": 1, ":ttl": now + 7200, ":limit": 48},
                "attribute_not_exists(requests) OR requests<:limit",
            )
        except Exception as exc:
            if (
                getattr(exc, "response", {}).get("Error", {}).get("Code")
                == "ConditionalCheckFailedException"
            ):
                raise GitHubError(429, (now // 3600 + 1) * 3600) from exc
            raise
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "RepoGuide",
        "X-GitHub-Api-Version": "2026-03-10",
    }
    if etag:
        headers["If-None-Match"] = etag
    try:
        with urlopen(
            Request("https://api.github.com" + path, headers=headers), timeout=6
        ) as response:
            raw = response.read(3000001)
            if len(raw) > 3000000:
                raise GitHubError(413)
            return json.loads(raw), dict(response.headers)
    except HTTPError as exc:
        if exc.code == 304:
            return None, dict(exc.headers)
        raise GitHubError(exc.code, exc.headers.get("X-RateLimit-Reset")) from None
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise GitHubError(503) from exc


def prepare_index(data, subject=None):
    from repoguide.git_utils import parse_github_url

    owner, name = parse_github_url(data["url"])
    repo, _ = request(f"/repos/{owner}/{name}")
    if repo.get("private"):
        raise ValueError("This demo supports public GitHub repositories only")
    if repo.get("size", 0) > 51200:
        raise ValueError(
            "Demo repositories must be smaller than 50 MiB in GitHub's size estimate"
        )
    branch = data.get("branch") or repo.get("default_branch")
    if (
        not isinstance(branch, str)
        or not branch
        or len(branch) > 200
        or any(ord(c) < 32 for c in branch)
    ):
        raise ValueError("Invalid or unavailable monitored branch")
    revision = data.get("commit_sha") or branch
    commit, _ = request(f"/repos/{owner}/{name}/commits/{quote(revision, safe='')}")
    if not re.fullmatch(r"[0-9a-f]{40}", commit.get("sha", "")):
        raise ValueError("GitHub returned an invalid revision")
    return {
        "url": "https://github.com/" + repo["full_name"],
        "commit_sha": commit["sha"],
        "branch": branch,
        "private": False,
        "force": bool(data.get("force", False)),
        "branch_explicit": bool(data.get("branch")),
        "resolved_from_branch": not bool(data.get("commit_sha")),
        "remote_checked_at": int(time.time()),
        "commit_message": commit.get("commit", {})
        .get("message", "")
        .split("\n")[0][:200],
    }


def check_update(repo, grant, subject):
    now = int(time.time())
    if now - int(grant.get("checked_at", 0)) < 600:
        return public_freshness(grant)
    try:
        # A conditional lease coalesces simultaneous browser/device checks.
        state.update(
            grant["pk"],
            "SET checking_until=:until",
            {":now": now, ":old": now - 600, ":until": now + 20},
            "(attribute_not_exists(checked_at) OR checked_at<:old) AND (attribute_not_exists(checking_until) OR checking_until<:now)",
        )
    except Exception as exc:
        if (
            getattr(exc, "response", {}).get("Error", {}).get("Code")
            == "ConditionalCheckFailedException"
        ):
            return public_freshness(state.get(grant["pk"]))
        raise
    try:
        branch = grant.get("monitored_branch")
        refresh_default = not branch or (
            not grant.get("branch_explicit")
            and now - int(grant.get("default_branch_checked_at", 0)) >= 3600
        )
        if refresh_default:
            prepared = prepare_index(
                {
                    "url": repo["url"],
                    "branch": branch if grant.get("branch_explicit") else None,
                },
                subject,
            )
        else:
            from repoguide.git_utils import parse_github_url

            owner, name = parse_github_url(repo["url"])
            commit, _ = request(
                f"/repos/{owner}/{name}/commits/{quote(branch, safe='')}"
            )
            prepared = {
                "branch": branch,
                "commit_sha": commit["sha"],
                "commit_message": commit.get("commit", {})
                .get("message", "")
                .split("\n")[0][:200],
            }
        result = {
            **grant,
            "checked_at": now,
            "monitored_branch": prepared["branch"],
            "remote_sha": prepared["commit_sha"],
            "freshness_status": "up_to_date"
            if prepared["commit_sha"] == repo["commit_sha"]
            else "update_available",
            "check_error": "",
            "remote_message": prepared.get("commit_message", ""),
            "default_branch_checked_at": now
            if refresh_default
            else grant.get("default_branch_checked_at", now),
        }
    except GitHubError as exc:
        result = {
            **grant,
            "checked_at": now,
            "freshness_status": "error",
            "check_error": "GitHub rate limit reached"
            if exc.status in {403, 429}
            else "GitHub access check failed",
            "retry_at": exc.retry_at,
        }
    except (ValueError, KeyError):
        result = {
            **grant,
            "checked_at": now,
            "freshness_status": "error",
            "check_error": "GitHub authorization or branch is unavailable",
        }
    state.update(
        grant["pk"],
        "SET checked_at=:at, freshness_status=:s, remote_sha=:sha, monitored_branch=:b, check_error=:e, remote_message=:m, default_branch_checked_at=:d REMOVE checking_until",
        {
            ":at": now,
            ":s": result["freshness_status"],
            ":sha": result.get("remote_sha", ""),
            ":b": result.get("monitored_branch", ""),
            ":e": result.get("check_error", ""),
            ":m": result.get("remote_message", ""),
            ":d": result.get("default_branch_checked_at", 0),
        },
    )
    return public_freshness(result)


def public_freshness(grant):
    return {
        k: grant.get(k)
        for k in (
            "freshness_status",
            "remote_sha",
            "monitored_branch",
            "checked_at",
            "check_error",
            "retry_at",
            "remote_message",
        )
    }
