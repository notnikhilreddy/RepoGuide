"""Collect sanitized deployment evidence without inventing absent acceptance.

--require-complete requires live functional, cutover, rollback and cleanup
evidence plus verified idle or the exact owner deferral. Neither skipped
quality nor skipped idle is represented as a passing measurement.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]
art = root / ".artifacts"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--require-complete", action="store_true")
args = parser.parse_args()


def read(name):
    path = art / name
    return json.loads(path.read_text()) if path.exists() else None


manifest = read("release-manifest.json")
native = read("aws-final-smoke.json")
idle = read("aws-idle-verification.json")
exception_path = root / "deployment/acceptance-exceptions.json"
exceptions = json.loads(exception_path.read_text()) if exception_path.exists() else {}
idle_skipped = (
    exceptions.get("release_id") == manifest["release_id"]
    and exceptions.get("idle_verification", {}).get("status") == "skipped_by_owner"
    and idle
    and idle.get("status") == "skipped_by_owner"
    and idle.get("final_services_zero") is True
)
production = read("browser-production-smoke.json")
security = read("aws-security-review.json")
preservation = read("neon-deployment-preservation.json")
rollback = read("aws-component-rollback.json")
cutover = read("vercel-cutover.json")
cleanup = read("deployment-cleanup.json")
drift = read("terraform-final-drift.json")
checks = {
    "native_exact_digest_functional": bool(
        native
        and native.get("passed")
        and native["release_id"] == manifest["release_id"]
    ),
    "live_iam_network_hardening": bool(
        security
        and security.get("security_groups_no_ingress")
        and all(
            v["all_linux_capabilities_dropped"]
            for v in security.get("task_hardening", {}).values()
        )
    ),
    "live_rate_limit": bool((read("aws-rate-verification.json") or {}).get("passed")),
    "original_neon_data_preserved": bool(preservation and preservation.get("passed")),
    "idle_verification_resolved": bool(idle_skipped)
    or bool(
        idle
        and idle.get("status") == "passed"
        and idle.get("minute_59_reset")
        and idle.get("final_services_zero")
    ),
    "component_rollback_restore": bool(
        rollback
        and rollback.get("passed")
        and rollback.get("release_id") == manifest["release_id"]
    ),
    "existing_vercel_domain_cutover": bool(cutover and cutover.get("passed")),
    "real_production_browser": bool(
        production
        and production.get("passed")
        and not production.get("readonly")
        and production.get("release_id") == manifest["release_id"]
    ),
    "cleanup_and_workers_zero": bool(
        cleanup
        and cleanup.get("passed")
        and cleanup.get("release_id") == manifest["release_id"]
    ),
    "terraform_no_drift": bool(
        drift
        and drift.get("passed")
        and drift.get("release_id") == manifest["release_id"]
    ),
}
report = {
    "created_at": datetime.now(timezone.utc).isoformat(),
    "release_id": manifest["release_id"],
    "source_sha256": manifest["source_sha256"],
    "source_status": manifest.get("source_status"),
    "quality": manifest["quality"],
    "acceptance_exceptions": exceptions,
    "real_idle_verification_passed": bool(idle and idle.get("status") == "passed"),
    "functional_acceptance_complete": all(checks.values()),
    "checks": checks,
    "images": {kind: uri.split("@", 1)[1] for kind, uri in manifest["images"].items()},
    "image_security": read("security-summary.json"),
    "image_sizes": read("ecr-sizes.json"),
    "packages": read("package-inventory.json"),
    "packaged_api_local": read("packaged-api-smoke.json"),
    "local_worker_contracts": read("local-workers.json"),
    "local_backend_startup": read("local-startup-smoke.json"),
    "native_functional": native,
    "native_memory_cpu": read("native-2g-metrics.json"),
    "api_resume_and_warm_reads": read("aws-neon-resume.json"),
    "neon_resume_observation": read("neon-resume-observation.json"),
    "neon_preservation_passed": bool(preservation and preservation.get("passed")),
    "idle": None if not idle else {k: v for k, v in idle.items() if k != "samples"},
    "production_browser": production,
    "rollback": rollback,
    "cutover": cutover,
    "cleanup": cleanup,
    "monitoring": read("aws-monitoring-review.json"),
    "known_secret_scan": read("source-secret-scan.json"),
    "ci_evaluation": "skipped_by_owner; no CI success or quality baseline claimed",
    "cost": "planning estimate only; same-day billing incomplete; see docs/deployment/cost-estimate.md",
}
(root / "reports").mkdir(exist_ok=True)
(root / "reports/deployment-validation.json").write_text(json.dumps(report, indent=2))
print(
    json.dumps(
        {
            "functional_acceptance_complete": report["functional_acceptance_complete"],
            "pending": [k for k, v in checks.items() if not v],
            "quality_status": report["quality"]["status"],
        }
    )
)
if args.require_complete:
    assert report["functional_acceptance_complete"], (
        "Required live acceptance evidence is incomplete"
    )
