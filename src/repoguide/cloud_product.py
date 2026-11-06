"""Tenant authorization and durable S3 conversations for the lightweight API.

S3 is authoritative for chat content. DynamoDB contains access grants and small
search/list metadata only. Conditional S3 writes prevent lost turns across tabs.
No prompt, answer or GitHub credential is stored in a listing index.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from repoguide import cloud_state as state


def namespace(subject):
    return hashlib.sha256(subject.encode()).hexdigest()


def identifier(value):
    return str(uuid.UUID(str(value)))


def s3():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        config=Config(connect_timeout=2, read_timeout=4, retries={"max_attempts": 2}),
    )


def bucket():
    return os.environ["REPOGUIDE_ARTIFACT_BUCKET"]


def catalog(partition, prefix, *, limit=100, cursor=None, ascending=False):
    args = dict(
        TableName=state.table(),
        IndexName="catalog",
        KeyConditionExpression="catalog_pk=:p AND begins_with(catalog_sk,:s)",
        ExpressionAttributeValues=state.encode({":p": partition, ":s": prefix}),
        ScanIndexForward=ascending,
        Limit=min(100, max(1, int(limit))),
    )
    if cursor:
        args["ExclusiveStartKey"] = cursor
    result = state.clients()[0].query(**args)
    return [state.decode(x) for x in result.get("Items", [])], result.get(
        "LastEvaluatedKey"
    )


def grant_repository(repo_id, subject, *, shared=False, branch=None, **extra):
    """Called only by the Index worker or an explicit admin migration."""
    repo_id = identifier(repo_id)
    existing = state.get("repository#" + repo_id)
    if existing and existing.get("owner_sub") != subject:
        # Content deduplication must never transfer another tenant's grant.
        raise state.Conflict("This index belongs to another account")
    row = {
        **existing,
        "pk": "repository#" + repo_id,
        "repo_id": repo_id,
        "owner_sub": subject,
        "visibility": "shared" if shared else "private",
        "catalog_pk": "shared" if shared else "user#" + subject,
        "catalog_sk": "repository#" + repo_id,
        "monitored_branch": branch or existing.get("monitored_branch", ""),
        **extra,
    }
    row.pop("superseded_by", None)
    state.clients()[0].put_item(TableName=state.table(), Item=state.encode(row))
    return row


def require_repository(repo_id, subject, *, write=False):
    row = state.get("repository#" + identifier(repo_id))
    if not row or (
        row.get("owner_sub") != subject and (write or row.get("visibility") != "shared")
    ):
        raise LookupError("Repository not found")
    return row


def repositories(subject):
    rows = []
    for partition in ("user#" + subject, "shared"):
        batch, _ = catalog(partition, "repository#")
        rows.extend(batch)
    # GSI membership is an optimization, never an authorization decision.
    return {
        r["repo_id"]: current
        for r in rows
        if (current := state.get(r["pk"]))
        and not current.get("superseded_by")
        and (
            current.get("owner_sub") == subject or current.get("visibility") == "shared"
        )
    }


def conversation_key(subject, conversation_id):
    return f"conversations/{namespace(subject)}/{identifier(conversation_id)}.json"


def metadata_key(subject, conversation_id):
    return f"conversation#{namespace(subject)}#{identifier(conversation_id)}"


def _metadata(subject, conversation_id):
    row = state.get(metadata_key(subject, conversation_id))
    if not row or row.get("deleted") or row.get("owner_sub") != subject:
        raise LookupError("Conversation not found")
    require_repository(row["repo_id"], subject)
    return row


def _read(subject, conversation_id):
    _metadata(subject, conversation_id)
    result = s3().get_object(
        Bucket=bucket(), Key=conversation_key(subject, conversation_id)
    )
    raw = result["Body"].read(800001)
    if len(raw) > 800000:
        raise ValueError("Conversation exceeds the storage limit")
    return json.loads(raw), result["ETag"]


def _json_number(value):
    # DynamoDB deserializes even integer event timestamps as Decimal. Keep the
    # durable S3 document ordinary JSON without stringifying numeric fields.
    if isinstance(value, Decimal) and value.is_finite():
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError("Unsupported conversation value")


def _write(subject, document, etag=None, *, create=False):
    if not create:
        _metadata(subject, document["id"])
    document["version"] = int(document.get("version", 0)) + 1
    document["updated_at"] = int(time.time() * 1000)
    raw = json.dumps(
        document, separators=(",", ":"), ensure_ascii=False, default=_json_number
    ).encode()
    if len(raw) > 600000:
        # Large answers remain durable in separate private S3 objects. Keep the
        # conversation manifest bounded rather than losing a completed answer.
        for message in document["messages"]:
            if not message.get("answer"):
                continue
            content = json.dumps(
                message["answer"],
                separators=(",", ":"),
                ensure_ascii=False,
                default=_json_number,
            ).encode()
            key = f"conversations/{namespace(subject)}/{document['id']}/{message['id']}-{hashlib.sha256(content).hexdigest()[:16]}.json"
            s3().put_object(
                Bucket=bucket(),
                Key=key,
                Body=content,
                ContentType="application/json",
                ServerSideEncryption="AES256",
            )
            message["answer_ref"] = key
            message.pop("answer", None)
            raw = json.dumps(
                document,
                separators=(",", ":"),
                ensure_ascii=False,
                default=_json_number,
            ).encode()
            if len(raw) <= 600000:
                break
    if len(raw) > 800000:
        raise ValueError("Conversation is full; start a new conversation")
    try:
        result = s3().put_object(
            Bucket=bucket(),
            Key=conversation_key(subject, document["id"]),
            Body=raw,
            ContentType="application/json",
            ServerSideEncryption="AES256",
            **({"IfNoneMatch": "*"} if create else {"IfMatch": etag}),
        )
    except Exception as exc:
        if getattr(exc, "response", {}).get("Error", {}).get("Code") in {
            "PreconditionFailed",
            "ConditionalRequestConflict",
            "412",
            "409",
        }:
            raise state.Conflict(
                "Conversation changed in another tab; refresh and retry"
            ) from exc
        raise
    row = {
        "pk": metadata_key(subject, document["id"]),
        "owner_sub": subject,
        "id": document["id"],
        "repo_id": document["repo_id"],
        "title": document["title"],
        "updated_at": document["updated_at"],
        "version": document["version"],
        "catalog_pk": "user#" + subject,
        "catalog_sk": f"conversation#{document['updated_at']:016d}#{document['id']}",
    }
    try:
        state.update(
            row["pk"],
            "SET " + ", ".join(f"{key}=:{key}" for key in row if key != "pk"),
            {
                **{":" + key: value for key, value in row.items() if key != "pk"},
                ":v": document["version"],
            },
            "attribute_not_exists(pk) OR (attribute_not_exists(deleted) AND version<:v)",
        )
    except Exception as exc:
        if (
            getattr(exc, "response", {}).get("Error", {}).get("Code")
            != "ConditionalCheckFailedException"
        ):
            raise
        # A newer S3 write or deletion already won. Never overwrite its metadata.
    return result["ETag"]


def create_conversation(subject, repo_id, title="New conversation"):
    require_repository(repo_id, subject)
    title = clean_title(title)
    document = {
        "id": str(uuid.uuid4()),
        "repo_id": identifier(repo_id),
        "title": title,
        "created_at": int(time.time() * 1000),
        "version": 0,
        "messages": [],
    }
    _write(subject, document, create=True)
    return document


def clean_title(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise ValueError("Conversation title must contain 1–120 characters")
    return " ".join(value.split())


def list_conversations(subject, query):
    repo_id, search = query.get("repo_id"), str(query.get("q", ""))[:120].casefold()
    cursor = None
    if query.get("cursor"):
        try:
            raw = str(query["cursor"])
            if len(raw) > 3000:
                raise ValueError("Cursor too large")
            cursor = json.loads(base64.urlsafe_b64decode(raw))
            if cursor.get("catalog_pk", {}).get(
                "S"
            ) != "user#" + subject or not cursor.get("catalog_sk", {}).get(
                "S", ""
            ).startswith("conversation#"):
                raise ValueError("Invalid cursor scope")
        except Exception as exc:
            raise ValueError("Invalid conversation cursor") from exc
    result = []
    for _ in range(6):
        rows, cursor = catalog(
            "user#" + subject, "conversation#", limit=50, cursor=cursor
        )
        for row in rows:
            if repo_id and row.get("repo_id") != repo_id:
                continue
            if search and search not in row.get("title", "").casefold():
                continue
            try:
                _metadata(subject, row["id"])
            except LookupError:
                continue
            result.append({k: row[k] for k in ("id", "repo_id", "title", "updated_at")})
        if len(result) >= 50 or not cursor:
            break
    if query.get("page") == "1":
        return {
            "items": result,
            "next_cursor": base64.urlsafe_b64encode(
                json.dumps(cursor).encode()
            ).decode()
            if cursor
            else None,
        }
    return result


def mutate(subject, conversation_id, callback):
    for attempt in range(4):
        document, etag = _read(subject, conversation_id)
        callback(document)
        try:
            _write(subject, document, etag)
            return document
        except state.Conflict:
            if attempt == 3:
                raise


def rename_conversation(subject, conversation_id, title):
    title = clean_title(title)
    mutate(subject, conversation_id, lambda d: d.update(title=title))
    return get_conversation(subject, conversation_id)


def delete_conversation(subject, conversation_id):
    _metadata(subject, conversation_id)
    state.update(
        metadata_key(subject, conversation_id),
        "SET deleted=:yes REMOVE catalog_pk, catalog_sk",
        {":yes": True},
    )
    job_id = state.get(metadata_key(subject, conversation_id)).get("active_job_id")
    if job_id:
        try:
            state.cancel_job(job_id, subject)
        except LookupError:
            pass
    s3().delete_object(Bucket=bucket(), Key=conversation_key(subject, conversation_id))
    prefix = f"conversations/{namespace(subject)}/{identifier(conversation_id)}/"
    objects = (
        s3()
        .list_objects_v2(Bucket=bucket(), Prefix=prefix, MaxKeys=1000)
        .get("Contents", [])
    )
    if objects:
        s3().delete_objects(
            Bucket=bucket(), Delete={"Objects": [{"Key": o["Key"]} for o in objects]}
        )
    return {"deleted": True}


def history_for(document):
    history = []
    for message in document["messages"][-8:]:
        if message["role"] == "user":
            history.append({"role": "user", "content": message["content"][:800]})
        elif message.get("status") == "complete" and message.get("answer"):
            answer = message["answer"]
            history.append(
                {
                    "role": "assistant",
                    "content": answer["answer"][:1200],
                    "paths": list(
                        dict.fromkeys(s["file_path"] for s in answer.get("sources", []))
                    )[:6],
                }
            )
    return history[-6:]


def attach_job(subject, conversation_id, turn_id, job):
    def change(document):
        for message in document["messages"]:
            if message["id"] == turn_id:
                message.update(job_id=job["id"], status=job["status"])

    return mutate(subject, conversation_id, change)


def complete_turn(subject, conversation_id, turn_id, job):
    stored = state.get("job#" + job["id"]) if job.get("id") else {}
    reference = stored.get("result_s3_key", "")
    expected = f"conversations/{namespace(subject)}/{identifier(conversation_id)}/"

    def change(document):
        for message in document["messages"]:
            if message["id"] == turn_id:
                message.update(
                    status=job["status"],
                    job_id=job["id"],
                    stage=job["stage"],
                    events=job.get("events", []),
                )
                if job["status"] in state.TERMINAL:
                    message.update(answer=job.get("result"), error=job.get("error"))
                    if reference.startswith(expected) and job.get("result"):
                        message["answer_ref"] = reference
                        message.pop("answer", None)
                    if document.get("active_turn") == turn_id:
                        document.pop("active_turn", None)

    document = mutate(subject, conversation_id, change)
    if job["status"] in state.TERMINAL and job.get("id"):
        settle_delivery(job["id"], subject)
    return document


def settle_delivery(job_id, subject):
    job = state.get("job#" + job_id)
    if job:
        state.update(
            "job#" + job_id,
            "SET expires_at=:ttl",
            {":ttl": int(time.time()) + 7 * 86400, ":owner": subject},
            "owner_sub=:owner",
        )
    state.clients()[0].delete_item(
        TableName=state.table(), Key=state.encode({"pk": "chat-delivery#" + job_id})
    )


def retry_chat_deliveries():
    """One due S3 retry after worker lifecycle reconciliation; bounded backoff."""
    rows, _ = catalog("chat-deliveries", "delivery#", limit=1, ascending=True)
    now = int(time.time())
    for row in rows:
        if int(row.get("due_at", 0)) > now:
            continue
        try:
            meta = state.get(metadata_key(row["owner_sub"], row["conversation_id"]))
            if meta.get("deleted"):
                settle_delivery(row["job_id"], row["owner_sub"])
                continue
            job = state.public_job(row["job_id"], row["owner_sub"])
            if not job and not state.get("job#" + row["job_id"]):
                settle_delivery(row["job_id"], row["owner_sub"])
            elif job and job["status"] in state.TERMINAL:
                complete_turn(
                    row["owner_sub"], row["conversation_id"], row["turn_id"], job
                )
        except Exception:
            due = now + min(3600, 60 * 2 ** min(6, int(row.get("delivery_attempt", 0))))
            try:
                state.update(
                    row["pk"],
                    "SET catalog_sk=:s, due_at=:due, delivery_attempt=if_not_exists(delivery_attempt,:zero)+:one",
                    {
                        ":s": f"delivery#{due:012d}#{row['job_id']}",
                        ":due": due,
                        ":zero": 0,
                        ":one": 1,
                        ":owner": row["owner_sub"],
                    },
                    "owner_sub=:owner",
                )
            except Exception:
                pass
            raise


def get_conversation(subject, conversation_id):
    document, _ = _read(subject, conversation_id)
    active = next(
        (m for m in document["messages"] if m["id"] == document.get("active_turn")),
        None,
    )
    if active:
        job_id = active.get("job_id")
        if not job_id:
            dedupe = hashlib.sha256(
                f"answer:{subject}:{active['id']}".encode()
            ).hexdigest()
            job_id = state.get("idempotency#" + dedupe).get("job_id")
        job = state.public_job(job_id, subject) if job_id else None
        if job:
            if job["status"] in state.TERMINAL or not active.get("job_id"):
                document = complete_turn(subject, conversation_id, active["id"], job)
            else:
                active.update(
                    status=job["status"],
                    stage=job["stage"],
                    job_id=job_id,
                    events=job.get("events", []),
                    cancel_requested=job.get("cancel_requested", False),
                )
        elif time.time() * 1000 - active["created_at"] > 120000:
            document = complete_turn(
                subject,
                conversation_id,
                active["id"],
                {
                    "id": None,
                    "status": "failed",
                    "stage": "failed",
                    "error": "Submission was interrupted. Your question was saved; send it again.",
                },
            )
    referenced = [m for m in document["messages"] if m.get("answer_ref")]

    def hydrate(message):
        expected = f"conversations/{namespace(subject)}/{identifier(conversation_id)}/"
        if not message["answer_ref"].startswith(expected):
            raise ValueError("Invalid saved answer reference")
        raw = (
            s3()
            .get_object(Bucket=bucket(), Key=message["answer_ref"])["Body"]
            .read(2000001)
        )
        if len(raw) > 2000000:
            raise ValueError("Saved answer exceeds the read limit")
        message["answer"] = json.loads(raw)

    if referenced:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(hydrate, referenced))
    return document


def submit_turn(subject, conversation_id, data, validate, charge):
    arguments = validate(data)
    turn_id = identifier(data.get("message_id"))
    document = get_conversation(subject, conversation_id)
    previous = next((m for m in document["messages"] if m["id"] == turn_id), None)
    if previous:
        if previous.get("job_id"):
            return {
                "job": state.public_job(previous["job_id"], subject),
                "conversation": document,
            }
        raise state.Conflict("This message is already being submitted")
    arguments.update(repo_id=document["repo_id"], history=history_for(document))
    arguments["conversation_id"], arguments["turn_id"] = conversation_id, turn_id
    charge(subject, "message")

    def reserve(current):
        if current.get("active_turn"):
            raise state.Conflict(
                "Wait for the current answer or stop it before sending another question"
            )
        if len(current["messages"]) >= 100:
            raise ValueError("This conversation is full; start a new conversation")
        now = int(time.time() * 1000)
        current["messages"].extend(
            [
                {
                    "id": str(uuid.uuid4()),
                    "role": "user",
                    "content": arguments["question"],
                    "created_at": now,
                },
                {
                    "id": turn_id,
                    "role": "assistant",
                    "status": "queued",
                    "created_at": now,
                },
            ]
        )
        current["active_turn"] = turn_id
        if current["title"] == "New conversation":
            current["title"] = " ".join(arguments["question"].split())[:100]

    mutate(subject, conversation_id, reserve)
    try:
        if state.control("answer").get("desired_state") != "on":
            raise state.Conflict(
                "Answer worker is offline; an administrator must start it"
            )
        charge(subject)
        job = state.submit("answer", subject, arguments, turn_id)
    except Exception as exc:
        complete_turn(
            subject,
            conversation_id,
            turn_id,
            {
                "id": None,
                "status": "failed",
                "stage": "failed",
                "error": str(exc)
                if isinstance(exc, state.Conflict)
                else "Question saved, but submission failed. Try again.",
            },
        )
        raise
    attach_job(subject, conversation_id, turn_id, job)
    return {"job": job, "conversation": get_conversation(subject, conversation_id)}


def record_usage(subject, values):
    day = time.strftime("%Y-%m-%d", time.gmtime())
    key = "usage#" + namespace(subject) + "#" + day
    counters = {
        k: max(0, int(v))
        for k, v in values.items()
        if k
        in {
            "requests",
            "input_tokens",
            "output_tokens",
            "estimated_cost_micros",
            "latency_ms",
            "indexed_files",
            "embedded_chunks",
            "reused_chunks",
            "answers",
            "abstentions",
            "valid_citations",
            "failed_requests",
            "cancelled_requests",
        }
    }
    if not counters:
        return
    state.update(
        key,
        "SET catalog_pk=:p, catalog_sk=:s, expires_at=:ttl ADD "
        + ", ".join(f"{k} :{k}" for k in counters),
        {
            ":p": "user#" + subject,
            ":s": "usage#" + day,
            ":ttl": int(time.time()) + 90 * 86400,
            **{":" + k: v for k, v in counters.items()},
        },
    )


def usage(subject):
    rows, _ = catalog("user#" + subject, "usage#", limit=31)
    return {
        "days": [
            {
                k: v
                for k, v in row.items()
                if k not in {"pk", "catalog_pk", "expires_at"}
            }
            for row in rows
        ],
        "cost_is_estimate": True,
    }
