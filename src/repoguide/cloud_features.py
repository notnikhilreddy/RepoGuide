"""Product HTTP routes; no framework, ORM or model dependencies."""

from __future__ import annotations

import hashlib
import json
import re
import time

from repoguide import cloud_product as product
from repoguide import cloud_state as state


def dispatch(
    method, path, query, event, subject, admin, *, configure, payload, validate, charge
):
    if path == "/api/jobs" and method == "GET":
        rows, _ = product.catalog("user#" + subject, "job#index#", limit=10)
        return 200, [
            job for row in rows if (job := state.public_job(row["id"], subject))
        ]
    if path == "/api/conversations":
        if method == "GET":
            return 200, product.list_conversations(subject, query)
        if method == "POST":
            data = payload(event)
            charge(subject, "conversation")
            return 201, product.create_conversation(
                subject, data.get("repo_id"), data.get("title", "New conversation")
            )
    match = re.fullmatch(r"/api/conversations/([0-9a-f-]+)(/messages)?", path)
    if match:
        conversation_id, messages = match.groups()
        if method == "GET" and not messages:
            return 200, product.get_conversation(subject, conversation_id)
        if method == "PATCH" and not messages:
            charge(subject, "metadata")
            return 200, product.rename_conversation(
                subject, conversation_id, payload(event).get("title")
            )
        if method == "DELETE" and not messages:
            return 200, product.delete_conversation(subject, conversation_id)
        if method == "POST" and messages:
            return 202, product.submit_turn(
                subject, conversation_id, payload(event), validate, charge
            )
    match = re.fullmatch(r"/(?:api/ui/)?jobs/([0-9a-f-]+)/cancel", path)
    if match and method == "POST":
        return 200, state.cancel_job(match[1], subject)
    if path == "/api/usage" and method == "GET":
        return 200, product.usage(subject)
    if path == "/feedback" and method == "POST":
        data = payload(event)
        if data.get("conversation_id"):
            document = product.get_conversation(subject, data["conversation_id"])
            message = next(
                (
                    m
                    for m in document["messages"]
                    if m["id"] == data.get("message_id")
                    and m["role"] == "assistant"
                    and m.get("answer")
                ),
                None,
            )
            if message is None or message.get("job_id") != data.get("job_id"):
                raise LookupError("Answer not found")
            job_id, trace_id = message["job_id"], message["answer"].get("trace_id")
            conversation_id, message_id = document["id"], message["id"]
        else:
            job = state.public_job(data.get("job_id"), subject)
            if not job or job["kind"] != "answer" or job["status"] != "complete":
                raise LookupError("Answer not found")
            job_payload = json.loads(state.get("job#" + job["id"])["payload"])
            job_id, trace_id = job["id"], (job.get("result") or {}).get("trace_id")
            conversation_id, message_id = (
                job_payload.get("conversation_id"),
                job_payload.get("turn_id"),
            )
        rating, category = data.get("rating"), data.get("category", "")
        if type(rating) is not int or rating not in {1, 2, 3, 4, 5}:
            raise ValueError("rating must be 1–5")
        if category not in {
            "helpful",
            "irrelevant",
            "incorrect",
            "missing_evidence",
            "bad_citation",
        }:
            raise ValueError("Invalid feedback category")
        charge(subject, "metadata")
        state.clients()[0].put_item(
            TableName=state.table(),
            Item=state.encode(
                {
                    "pk": "feedback#" + job_id + "#" + product.namespace(subject),
                    "owner_sub": subject,
                    "job_id": job_id,
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "trace_id": trace_id,
                    "rating": rating,
                    "category": category,
                    "created_at": int(time.time()),
                    "expires_at": int(time.time()) + 90 * 86400,
                }
            ),
        )
        return 200, {"recorded": True}
    match = re.fullmatch(
        r"/repositories/([0-9a-f-]+)/(check-update|update|architecture|health)", path
    )
    if match:
        repo_id, action = match.groups()
        grant = product.require_repository(repo_id, subject, write=action == "update")
        configure()
        from repoguide import cloud_reads as reads

        if action in {"architecture", "health"} and method == "GET":
            from repoguide.repository_views import architecture, health

            with reads.database() as db:
                return 200, (
                    architecture(db, repo_id, query)
                    if action == "architecture"
                    else health(db, repo_id, grant)
                )
        if action == "check-update" and method == "POST":
            from repoguide.github_api import check_update

            with reads.database() as db:
                repo = reads.repository(db, repo_id)
            return 200, check_update(repo, grant, subject)
        if action == "update" and method == "POST":
            from repoguide.github_api import prepare_index

            with reads.database() as db:
                repo = reads.repository(db, repo_id)
            if not grant.get("remote_sha") or grant["remote_sha"] == repo["commit_sha"]:
                raise state.Conflict("Check for updates before updating the index")
            args = prepare_index(
                {"url": repo["url"], "branch": grant.get("monitored_branch")}, subject
            )
            args.update(base_repo_id=repo_id, force=False)
            args["branch_explicit"] = grant.get("branch_explicit", False)
            charge(subject, "index")
            key = "update:" + repo_id + ":" + args["commit_sha"]
            for _ in range(10):
                existing = state.get(
                    "idempotency#"
                    + hashlib.sha256(f"index:{subject}:{key}".encode()).hexdigest()
                )
                if not existing:
                    break
                previous = state.public_job(existing["job_id"], subject)
                if previous and previous["status"] in {"failed", "cancelled"}:
                    key += "-retry-" + previous["id"]
                else:
                    break
            return 202, state.submit("index", subject, args, key)
    return None
