"""Safely merge additional RepoGuide settings into an EXISTING SSM SecureString.

Does not print existing values. Empty lines are skipped to avoid clearing secrets.
Usage:
  uv run python scripts/update_runtime_settings.py --env-file .env.deploy.additions --dry-run
  uv run python scripts/update_runtime_settings.py --env-file .env.deploy.additions
"""
from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path

# Exactly the Settings fields intended for AWS runtime. Never accept arbitrary keys.
ALLOWED = frozenset({
    "DATABASE_URL", "LLM_PROVIDER", "GEMINI_API_KEY", "GEMINI_MODEL",
    "OPENCODE_API_KEY", "OPENCODE_BASE_URL", "OPENCODE_MODEL",
    "OLLAMA_BASE_URL", "OLLAMA_MODEL",
    "CONTEXT7_API_KEY", "GITHUB_PERSONAL_ACCESS_TOKEN", "REDIS_URL",
    "MLFLOW_ENABLED", "MLFLOW_TRACKING_URI", "MLFLOW_EXPERIMENT",
    "MLFLOW_CAPTURE_CONTENT", "MLFLOW_AUTOLOG", "ROUTER_PROVIDER",
    "JEV_API_KEY", "JEV_ENDPOINT", "JEV_MODEL",
    "ROUTER_SUFFICIENCY_THRESHOLD",
})


def load_additions(path: Path) -> tuple[dict[str, str], list[str]]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing local additions file: {path}")
    if path.stat().st_mode & (stat.S_IRGRP | stat.S_IROTH):
        raise PermissionError("Run chmod 600 on the additions file")
    additions: dict[str, str] = {}
    skipped = []
    for num, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or key not in ALLOWED:
            raise ValueError(f"Line {num}: invalid or unsupported setting {key!r}")
        if key in additions:
            raise ValueError(f"Line {num}: duplicate setting {key}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not value:
            skipped.append(key)
            continue
        additions[key] = value
    if additions.get("LLM_PROVIDER") not in (None, "gemini", "opencode", "ollama"):
        raise ValueError("LLM_PROVIDER must be gemini, opencode, or ollama")
    if additions.get("ROUTER_PROVIDER") not in (None, "llm", "jev"):
        raise ValueError("ROUTER_PROVIDER must be llm or jev")
    for key in ("MLFLOW_ENABLED", "MLFLOW_CAPTURE_CONTENT", "MLFLOW_AUTOLOG"):
        if key in additions and additions[key].lower() not in ("true", "false"):
            raise ValueError(f"{key} must be true or false")
    if "ROUTER_SUFFICIENCY_THRESHOLD" in additions:
        t = float(additions["ROUTER_SUFFICIENCY_THRESHOLD"])
        if not 0 <= t <= 1:
            raise ValueError("ROUTER_SUFFICIENCY_THRESHOLD must be between 0 and 1")
    return additions, skipped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", default=".env.deploy.additions")
    ap.add_argument("--name", default="/repoguide/demo/runtime")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    additions, skipped = load_additions(Path(args.env_file))
    import boto3
    ssm = boto3.client("ssm")
    response = ssm.get_parameter(Name=args.name, WithDecryption=True)
    if response["Parameter"]["Type"] != "SecureString":
        raise ValueError("Existing SSM parameter is not a SecureString; refusing update")
    existing = json.loads(response["Parameter"]["Value"])
    if not isinstance(existing, dict) or not all(
        isinstance(k, str) and k in ALLOWED and isinstance(v, str)
        for k, v in existing.items()
    ):
        raise ValueError("Existing runtime settings JSON is invalid or contains unexpected keys")
    merged = {**existing, **additions}
    if not merged.get("DATABASE_URL"):
        raise ValueError("DATABASE_URL missing in existing or new settings")
    if merged.get("LLM_PROVIDER", "gemini") == "gemini" and not merged.get("GEMINI_API_KEY"):
        raise ValueError("Gemini selected, but GEMINI_API_KEY is missing")
    raw = json.dumps(merged, separators=(",", ":"))
    if len(raw.encode("utf-8")) > 4096:
        raise ValueError("Merged JSON exceeds the SSM Standard parameter 4 KiB limit")
    print("SSM parameter:", args.name)
    print("Adding/updating keys (values hidden):", ", ".join(sorted(additions)) or "none")
    print("Blank keys ignored:", ", ".join(sorted(skipped)) or "none")
    print("Total retained keys:", len(merged))
    if args.dry_run:
        print("Dry run: no changes written")
    elif merged != existing:
        ssm.put_parameter(Name=args.name, Value=raw, Type="SecureString", Overwrite=True)
        print("SSM SecureString updated; existing keys retained")
    else:
        print("No changes needed")


if __name__ == "__main__":
    main()
