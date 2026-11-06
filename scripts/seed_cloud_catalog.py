"""Publish real datasets and optionally measured release reports to private S3.

Preview is read-only. Existing reports are preserved; publishing release scores
requires the strict quality gate and never manufactures missing measurements.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from repoguide.evaluation_metrics import file_recall, hit_at_k, mrr

ROOT = Path(__file__).resolve().parents[1]


def public_report(name, measured, corpus, comparison=None):
    if (
        measured.get("complete") is not True
        or measured.get("live_generation") is not True
    ):
        raise ValueError("Only complete live measurements may be published")
    cases = {c["id"]: c for c in corpus["cases"]}
    if measured.get("case_ids") != list(cases):
        raise ValueError("Measured corpus mismatch")
    results = []
    for row in measured["cases"]:
        case = cases[row["id"]]
        observed = list(
            dict.fromkeys(s["file_path"] for s in row["answer"]["sources"])
        )[:8]
        results.append(
            {
                "question": case["question"],
                "repetition": row["repetition"],
                "expected_paths": case["expected_paths"],
                "observed_paths": observed,
                "hit_at_8": hit_at_k(case["expected_paths"], observed, 8)
                if case["expected_paths"]
                else None,
                "file_recall_at_8": file_recall(case["expected_paths"], observed, 8)
                if case["expected_paths"]
                else None,
                "mrr_at_8": mrr(case["expected_paths"], observed, 8)
                if case["expected_paths"]
                else None,
                "latency_ms": round(row["latency_seconds"] * 1000),
                "answer": row["answer"]["answer"],
                "trace_id": row["answer"].get("trace_id"),
            }
        )
    if len(results) != len(cases) * measured["repeats"]:
        raise ValueError("Measured passes are incomplete")
    report = {
        "name": name,
        "results": results,
        "aggregate": measured["retrieval_modes"],
        "quality_metrics": measured["metrics"],
        "performance": measured["performance"],
        "source_sha256": measured["source_sha256"],
        "fixture_commit": measured["metadata"]["fixture_commit"],
        "notes": f"{len(cases)} pinned questions × {measured['repeats']} uncached passes. Fixture {measured['metadata']['fixture_commit'][:12]}. Hardware: {measured['metadata']['hardware']}. Warm latency excludes startup. The chart measures raw retrieval modes; case paths show final selected evidence.",
    }
    if comparison:
        report["comparison"] = comparison
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--release-reports", action="store_true")
    args = parser.parse_args()
    out = json.loads(
        subprocess.check_output(
            ["terraform", "-chdir=" + str(ROOT / "infra/terraform"), "output", "-json"],
            text=True,
        )
    )
    bucket = out["artifact_bucket"]["value"]
    s3 = boto3.Session(profile_name="repoguide", region_name="us-east-2").client("s3")
    try:
        existing = s3.get_object(Bucket=bucket, Key="evaluations/catalog.json")
        previous = json.loads(existing["Body"].read())
        condition = {"IfMatch": existing["ETag"]}
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {"NoSuchKey", "404"}:
            raise
        previous = {"datasets": [], "reports": []}
        condition = {"IfNoneMatch": "*"}
    raw = (ROOT / "evals/release_cases.json").read_bytes()
    corpus = json.loads(raw)
    entry = {"name": "release_cases.json", "cases": len(corpus["cases"])}
    catalog = {
        **previous,
        "datasets": [
            d for d in previous.get("datasets", []) if d["name"] != entry["name"]
        ]
        + [entry],
    }
    objects = {"evaluations/datasets/" + entry["name"]: raw}
    if args.release_reports:
        from release_cloud import verify

        if verify()["status"] != "passed":
            raise ValueError("Passing live comparison required")
        manifest = json.loads((ROOT / ".artifacts/release-manifest.json").read_text())
        before = json.loads((ROOT / ".artifacts/baseline-evaluation.json").read_text())
        after = json.loads((ROOT / ".artifacts/candidate-evaluation.json").read_text())
        comparison = {"before": before["metrics"], "after": after["metrics"]}
        reports = list(previous.get("reports", []))
        for phase, measured in [("baseline", before), ("candidate", after)]:
            name = manifest["release_id"] + "-" + phase + ".json"
            document = public_report(
                name, measured, corpus, comparison if phase == "candidate" else None
            )
            if (
                phase == "candidate"
                and manifest["quality"].get("acceptance")
                == "owner_accepted_measured_tradeoffs"
            ):
                document["notes"] += (
                    " Two questions showed minor relevance/citation-scoring regressions; this release was accepted with those measured tradeoffs."
                )
            objects["evaluations/" + name] = json.dumps(
                document, ensure_ascii=False, separators=(",", ":")
            ).encode()
            reports = [r for r in reports if r["name"] != name] + [
                {"name": name, "cases": len(document["results"])}
            ]
        catalog.update(
            reports=reports, quality_status="passed", release_id=manifest["release_id"]
        )
    if not catalog.get("reports") and "quality_status" not in catalog:
        catalog["quality_status"] = "not_measured"
    objects["evaluations/catalog.json"] = json.dumps(catalog).encode()
    receipts = []
    if args.apply:
        for key, content in objects.items():
            result = s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=content,
                ContentType="application/json",
                ServerSideEncryption="AES256",
                **(condition if key.endswith("/catalog.json") else {}),
            )
            receipts.append(
                {
                    "key": key,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "version": result["VersionId"],
                }
            )
        (ROOT / ".artifacts/published-evaluation-catalog.json").write_text(
            json.dumps(
                {
                    "passed": True,
                    "release_id": catalog.get("release_id"),
                    "objects": receipts,
                    "reports": catalog.get("reports", []),
                },
                indent=2,
            )
        )
    print(
        json.dumps(
            {
                "applied": args.apply,
                "dataset": entry,
                "report_count": len(catalog.get("reports", [])),
            }
        )
    )


if __name__ == "__main__":
    main()
