"""Replace the complete SSM SecureString payload with the local .env.deploy.

Includes empty values and removes keys absent from the file. Values are literal:
no shell evaluation, variable expansion, multiline values, or inline comments.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def load_settings(path: Path) -> dict[str, str]:
    settings: dict[str, str] = {}
    for num, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"Line {num}: expected KEY=value (value hidden)")
        value = value.strip()
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"Line {num}: unmatched quote (value hidden)")
            value = value[1:-1]
        settings[key] = value
    return settings


def sync_settings(
    ssm,
    name: str,
    settings: dict[str, str],
    *,
    dry_run: bool = False,
    kms_key_id: str | None = None,
) -> bool:
    """Write the exact local object in one call, without fetching remote values."""
    print("SSM parameter:", name)
    print("Local settings:", len(settings), "(values hidden; empty values included)")
    if dry_run:
        print("Dry run: complete replacement prepared; no AWS calls made")
        return False
    request = dict(
        Name=name,
        Value=json.dumps(settings, separators=(",", ":")),
        Type="SecureString",
        Overwrite=True,
    )
    if kms_key_id:
        request["KeyId"] = kms_key_id
    response = ssm.put_parameter(**request)
    print("SSM SecureString replaced; version:", response["Version"])
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--env-file", default=".env.deploy")
    ap.add_argument("--name", default="/repoguide/demo/runtime")
    ap.add_argument(
        "--profile", help="AWS profile (otherwise use the AWS credential chain)"
    )
    ap.add_argument("--region", help="AWS region (otherwise use AWS region settings)")
    ap.add_argument(
        "--kms-key-id", help="KMS key ID/ARN; otherwise AWS uses its default SSM key"
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Prepare the replacement locally without contacting AWS",
    )
    args = ap.parse_args()
    try:
        settings = load_settings(Path(args.env_file))
        if args.dry_run:
            sync_settings(None, args.name, settings, dry_run=True)
            return
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            ssm = boto3.Session(
                profile_name=args.profile, region_name=args.region
            ).client("ssm")
            sync_settings(ssm, args.name, settings, kms_key_id=args.kms_key_id)
        except (BotoCoreError, ClientError) as exc:
            code = (
                exc.response["Error"]["Code"]
                if isinstance(exc, ClientError)
                else type(exc).__name__
            )
            ap.exit(
                1,
                f"AWS request failed ({code}); check profile, region, parameter name and permissions\n",
            )
    except (ValueError, OSError) as exc:
        ap.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
