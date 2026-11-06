"""Python ZIP HTTP API v2 handler. Health imports only the standard library."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from urllib.parse import urlparse

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def json_default(value):
    if isinstance(value, Decimal):
        return int(value) if value == int(value) else float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def response(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(body, default=json_default, separators=(",", ":")),
    }


def identity(event):
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    if not claims.get("sub") or claims.get("token_use") != "access":
        raise ApiError(401, "Authenticated access token required")
    if claims.get("iss") != os.environ.get("REPOGUIDE_COGNITO_ISSUER") or claims.get(
        "client_id"
    ) != os.environ.get("REPOGUIDE_COGNITO_CLIENT_ID"):
        raise ApiError(401, "Unexpected token issuer or client")
    raw = claims.get("cognito:groups", [])
    groups = re.findall(r"[\w-]+", raw) if isinstance(raw, str) else raw
    return claims["sub"], "repoguide-admins" in groups


@lru_cache(maxsize=1)
def configure():
    import boto3
    from botocore.config import Config

    # API role reads this exact parameter only, never worker credentials.
    value = boto3.client(
        "ssm",
        config=Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 1}),
    ).get_parameter(Name=os.environ["REPOGUIDE_API_SSM_PARAMETER"], WithDecryption=True)
    config = json.loads(value["Parameter"]["Value"])
    allowed = {
        "READ_DATABASE_URL",
        "UPSTASH_REDIS_REST_URL",
        "UPSTASH_REDIS_REST_TOKEN",
    }
    if not isinstance(config, dict) or any(
        k not in allowed or not isinstance(v, str) for k, v in config.items()
    ):
        raise ValueError("Invalid read API configuration")
    os.environ.update(config)


def payload(event):
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw, validate=True).decode()
    if len(raw) > 12000:
        raise ApiError(413, "Request too large")
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("Expected a JSON object")
    return obj


def budget(subject, kind="answer"):
    import time

    from repoguide.cloud_state import update

    now = int(time.time())
    for window, width, limit in [
        ("minute", 60, 20 if kind == "metadata" else 5),
        ("day", 86400, 3 if kind == "index" else 200 if kind == "metadata" else 30),
    ]:
        bucket = now // width
        try:
            update(
                f"limit#{subject}#{kind}#{window}#{bucket}",
                "SET requests=if_not_exists(requests,:zero)+:one, expires_at=:ttl",
                {":zero": 0, ":one": 1, ":ttl": (bucket + 2) * width, ":limit": limit},
                "attribute_not_exists(requests) OR requests<:limit",
            )
        except Exception as exc:
            if (
                getattr(exc, "response", {}).get("Error", {}).get("Code")
                == "ConditionalCheckFailedException"
            ):
                raise ApiError(
                    429, "Per-user " + window + " job limit reached"
                ) from exc
            raise
    if kind in {"answer", "index"}:
        try:
            update(
                f"global-limit#{kind}#{now // 86400}",
                "SET requests=if_not_exists(requests,:zero)+:one, expires_at=:ttl",
                {
                    ":zero": 0,
                    ":one": 1,
                    ":ttl": now + 172800,
                    ":limit": 10 if kind == "index" else 100,
                },
                "attribute_not_exists(requests) OR requests<:limit",
            )
        except Exception as exc:
            if (
                getattr(exc, "response", {}).get("Error", {}).get("Code")
                == "ConditionalCheckFailedException"
            ):
                raise ApiError(
                    429, "The demo's shared daily job allowance has been reached"
                ) from exc
            raise


def validate_answer(data):
    question = data.get("question", "")
    if not isinstance(question, str) or not 3 <= len(question.strip()) <= 2000:
        raise ValueError("Question must contain 3–2000 characters")
    result = {"question": question.strip()}
    for key, default, allowed in [
        ("docs_policy", "auto", {"auto", "always", "never"}),
        (
            "retrieval_mode",
            "hybrid",
            {
                "dense",
                "graph",
                "keyword",
                "hybrid",
                "hybrid_rerank",
                "hybrid_graph",
                "hybrid_graph_rerank",
            },
        ),
        ("answer_depth", "auto", {"auto", "concise", "standard", "detailed"}),
    ]:
        value = data.get(key, default)
        if not isinstance(value, str) or value not in allowed:
            raise ValueError("Invalid " + key)
        result[key] = value
    top_k = data.get("top_k", 8)
    if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 12:
        raise ValueError("top_k must be 1–12")
    result["top_k"] = top_k
    focus = data.get("focus")
    if focus is not None:
        from repoguide.cloud_reads import path_check

        if not isinstance(focus, dict):
            raise ValueError("Invalid source context")
        safe_focus = {"path": path_check(focus.get("path", ""))}
        for key in ("start_line", "end_line"):
            if key in focus:
                if type(focus[key]) is not int or not 1 <= focus[key] <= 100000:
                    raise ValueError("Invalid source line")
                safe_focus[key] = focus[key]
        if safe_focus.get("end_line", 0) and safe_focus["end_line"] < safe_focus.get(
            "start_line", 1
        ):
            raise ValueError("Invalid source range")
        result["focus"] = safe_focus
    return result


def validate_index(data):
    url = data.get("url", "")
    if not isinstance(url, str) or len(url) > 300:
        raise ValueError("Invalid GitHub URL")
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username
        or parsed.password
        or parsed.port
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Only HTTPS github.com repository URLs are supported")
    if not re.fullmatch(r"/[A-Za-z0-9-]+/[A-Za-z0-9_.-]+/?", parsed.path):
        raise ValueError("Expected a GitHub owner/repository URL")
    commit = data.get("commit_sha")
    if commit is not None and not re.fullmatch(r"[0-9a-f]{40}", str(commit)):
        raise ValueError("commit_sha must be a full commit hash")
    if not isinstance(data.get("force", False), bool):
        raise ValueError("force must be boolean")
    return {
        "url": f"https://github.com{parsed.path.rstrip('/').removesuffix('.git')}",
        "force": data.get("force", False),
        **({"commit_sha": commit} if commit else {}),
    }


def evaluation_route(path):
    import boto3

    s3 = boto3.client("s3")
    key = (
        "evaluations/catalog.json"
        if path == "/api/ui/evaluations"
        else "evaluations/" + path.rsplit("/", 1)[-1]
    )
    if path != "/api/ui/evaluations" and not re.fullmatch(
        r"[\w-]+\.json", key.rsplit("/", 1)[-1]
    ):
        raise LookupError("Unknown report")
    try:
        raw = s3.get_object(Bucket=os.environ["REPOGUIDE_ARTIFACT_BUCKET"], Key=key)[
            "Body"
        ].read(2000000)
        return json.loads(raw)
    except s3.exceptions.NoSuchKey:
        if path == "/api/ui/evaluations":
            return {"datasets": [], "reports": []}
        raise LookupError("Report not found") from None


def handler(event, context):
    path = event.get("rawPath", "/")
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    if method == "OPTIONS":
        # Gateway supplies the configured origin/method/header allowlist. Its
        # explicit unauthenticated OPTIONS integration must return success.
        return {"statusCode": 204, "headers": {"cache-control": "no-store"}, "body": ""}
    if method == "GET" and path == "/health":
        return response(
            200,
            {
                "status": "ok",
                "service": "repoguide-read-api",
                "release": os.getenv("REPOGUIDE_RELEASE", "local"),
            },
        )
    try:
        subject, admin = identity(event)
        from repoguide import cloud_product as product
        from repoguide import cloud_reads as reads
        from repoguide import cloud_state as state
        from repoguide.cloud_features import dispatch

        query = event.get("queryStringParameters") or {}
        feature = dispatch(
            method,
            path,
            query,
            event,
            subject,
            admin,
            configure=configure,
            payload=payload,
            validate=validate_answer,
            charge=budget,
        )
        if feature is not None:
            return response(*feature)
        if method == "GET" and path == "/api/compute/status":
            return response(
                200,
                {"admin": admin, "workers": {k: state.status(k) for k in state.KINDS}},
            )
        match = re.fullmatch(r"/api/compute/(answer|index)/(start|stop)", path)
        if method == "POST" and match:
            if not admin:
                raise ApiError(403, "Administrator permissions required")
            data = payload(event)
            kind, action = match.groups()
            if action == "start":
                result = state.start_service(kind, subject)
            else:
                force = data.get("force", False)
                if not isinstance(force, bool):
                    raise ValueError("force must be boolean")
                result = state.stop_service(kind, subject, force)
            log.warning(
                json.dumps(
                    {
                        "action": action,
                        "kind": kind,
                        "actor": subject,
                        "generation": result.get("generation"),
                    }
                )
            )
            return response(
                202,
                {k: v for k, v in result.items() if k not in {"operation_token", "pk"}},
            )
        match = re.fullmatch(r"/(?:api/ui/)?jobs/([0-9a-f-]+)", path)
        if method == "GET" and match:
            job = state.public_job(match[1], subject)
            if job is None:
                raise LookupError("Unknown or expired job")
            return response(200, job)
        if method == "POST":
            data = payload(event)
            key = (event.get("headers") or {}).get("idempotency-key", str(uuid.uuid4()))
            if len(key) > 150:
                raise ValueError("Idempotency key too long")
            match = re.fullmatch(r"/repositories/([0-9a-f-]+)/ask/robust", path)
            if path in {"/ask-jobs", "/api/ui/ask-jobs"} or match:
                args = validate_answer(data)
                args["repo_id"] = (
                    match[1] if match else str(uuid.UUID(data.get("repo_id", "")))
                )
                if state.control("answer").get("desired_state") != "on":
                    raise state.Conflict(
                        "Answer worker is offline; an administrator must start it"
                    )
                configure()
                product.require_repository(args["repo_id"], subject)
                with reads.database() as db:
                    if reads.repository(db, args["repo_id"])["status"] != "indexed":
                        raise ApiError(409, "Repository is not indexed")
                budget(subject)
                return response(202, state.submit("answer", subject, args, key))
            if path in {"/index-jobs", "/api/ui/index-jobs"}:
                args = validate_index(data)
                if state.control("index").get("desired_state") != "on":
                    raise state.Conflict(
                        "Indexer is offline; an administrator must start it"
                    )
                budget(subject, "index")
                configure()
                from repoguide.github_api import prepare_index

                args = prepare_index({**args, "branch": data.get("branch")}, subject)
                with reads.database() as db:
                    capacity = db.execute(
                        "SELECT pg_database_size(current_database()) AS bytes,(SELECT count(*) FROM chunks) AS chunks"
                    ).fetchone()
                    if (
                        capacity["bytes"] > 350 * 1024 * 1024
                        or capacity["chunks"] > 50000
                    ):
                        raise ApiError(
                            429,
                            "The demo's shared index storage allowance has been reached",
                        )
                    previous = db.execute(
                        "SELECT id FROM repositories WHERE owner_sub=%s AND url=%s AND status='indexed' ORDER BY created_at DESC LIMIT 1",
                        (subject, args["url"]),
                    ).fetchone()
                if previous:
                    if not state.get("repository#" + previous["id"]):
                        product.grant_repository(
                            previous["id"], subject, branch=args.get("branch")
                        )
                    product.require_repository(previous["id"], subject, write=True)
                    args["base_repo_id"] = previous["id"]
                elif (
                    sum(
                        g.get("owner_sub") == subject
                        for g in product.repositories(subject).values()
                    )
                    >= 10
                ):
                    raise ApiError(
                        429, "The demo allows ten active repositories per account"
                    )
                return response(202, state.submit("index", subject, args, key))
            if path == "/api/ui/evaluation-jobs":
                raise ApiError(403, "Use the protected evaluation release workflow")
            raise LookupError("Unknown route")
        if method != "GET":
            raise ApiError(405, "Method not allowed")
        if path.startswith("/api/ui/evaluations"):
            return response(200, evaluation_route(path))
        if path not in {"/ready", "/api/ui/repositories"} and not re.fullmatch(
            r"/(?:api/ui/repositories/[0-9a-f-]+/(?:overview|files|file|symbols-in-file)|repositories/[0-9a-f-]+/(?:graph|dependencies|symbols))",
            path,
        ):
            raise LookupError("Unknown route")
        configure()
        if path == "/api/ui/repositories":
            grants = product.repositories(subject)
            rows = reads.browse(path, query, allowed_ids=grants)
            for row in rows:
                row.pop("owner_sub", None)
                grant = grants[row["id"]]
                row.update(
                    {
                        k: grant.get(k)
                        for k in (
                            "visibility",
                            "monitored_branch",
                            "freshness_status",
                            "remote_sha",
                            "checked_at",
                            "check_error",
                        )
                    }
                )
                row["can_update"] = grant.get("owner_sub") == subject
            return response(200, rows)
        if path != "/ready":
            match = re.search(r"/(?:repositories)/([0-9a-f-]+)/", path)
            if match:
                product.require_repository(match[1], subject)
        return response(200, reads.browse(path, query))
    except ApiError as exc:
        return response(exc.status, {"detail": exc.message})
    except (ValueError, TypeError) as exc:
        # Never emit arbitrary SDK/database exceptions containing credentials.
        message = (
            str(exc)
            if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError)
            else "Invalid request"
        )
        return response(422, {"detail": message[:200]})
    except KeyError:
        return response(503, {"detail": "Service configuration unavailable"})
    except LookupError:
        return response(404, {"detail": "Resource not found"})
    except Exception as exc:
        from repoguide.cloud_state import Conflict
        from repoguide.github_api import GitHubError

        if isinstance(exc, GitHubError):
            return response(
                429
                if exc.status in {403, 429}
                else 422
                if exc.status in {404, 422}
                else 503,
                {
                    "detail": "GitHub request limit reached; try again later"
                    if exc.status in {403, 429}
                    else "Only accessible public GitHub repositories and valid branches are supported"
                    if exc.status in {404, 422}
                    else "GitHub is temporarily unavailable",
                    "retry_at": exc.retry_at,
                },
            )

        if isinstance(exc, Conflict):
            return response(409, {"detail": str(exc)})
        code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if code in {"ConditionalCheckFailedException", "TransactionCanceledException"}:
            return response(409, {"detail": "State changed; refresh and retry"})
        log.error(
            json.dumps(
                {
                    "error_type": type(exc).__name__,
                    "request_id": getattr(context, "aws_request_id", None),
                }
            )
        )
        return response(
            503,
            {
                "detail": "Database unavailable"
                if path == "/ready"
                else "Service temporarily unavailable"
            },
        )
