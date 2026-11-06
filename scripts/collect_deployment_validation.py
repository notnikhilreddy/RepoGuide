"""Collect sanitized deployment evidence without inventing absent acceptance.

--require-complete requires live functional, cutover, rollback and cleanup
evidence plus the real idle test and product isolation/update checks. Skipped
quality or historical acceptance evidence cannot satisfy this product release.
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
production = read("browser-production-smoke.json")
security = read("aws-security-review.json")
preservation = read("neon-deployment-preservation.json")
rollback = read("aws-component-rollback.json")
cutover = read("vercel-cutover.json")
cleanup = read("deployment-cleanup.json")
drift = read("terraform-final-drift.json")
product = read("product-live-api-smoke.json")
metrics = read("native-2g-metrics.json") or {}


def current_pass(name):
    evidence = read(name) or {}
    return bool(
        evidence.get("passed") is True
        and evidence.get("release_id") == manifest["release_id"]
    )


checks = {
    "measured_quality_gate": manifest["quality"]["status"] == "passed",
    "owner_scoped_s3_and_api": current_pass("product-live-api-smoke.json"),
    "public_registration_enabled": bool(
        product
        and current_pass("product-live-api-smoke.json")
        and product.get("public_registration_enabled") is True
    ),
    "real_incremental_update_and_browser": current_pass(
        "product-incremental-live-smoke.json"
    ),
    "published_measured_evaluations": current_pass("published-evaluation-catalog.json"),
    "verified_unused_cloud_cleanup": current_pass("product-cloud-cleanup.json"),
    "verified_unused_vercel_cleanup": current_pass("product-vercel-cleanup.json"),
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
    "live_rate_limit": current_pass("aws-rate-verification.json"),
    "original_neon_data_preserved": bool(preservation and preservation.get("passed")),
    "idle_verification_resolved": bool(
        idle
        and idle.get("release_id") == manifest["release_id"]
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
    "ci_evaluation": "No remote CI success claimed; paired local live evaluation and exact-image checks are recorded separately.",
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
    native_checks = native.get("checks", {})
    browser_checks = production.get("checks", {})
    expected_digests = {uri.split("@")[-1] for uri in manifest["images"].values()}
    measured_digests = {
        image["digest"]
        for task in native.get("tasks", [])
        for image in task.get("images", [])
    }
    smoke = {
        "release_id": manifest["release_id"],
        "live_aws": native.get("live_aws") is True and idle.get("live_aws") is True,
        "live_cognito": native.get("live_cognito") is True
        and production.get("live_cognito") is True,
        "live_vercel": production.get("live_vercel") is True,
        "browsing_workers_zero": native_checks.get("browsing_workers_zero") is True
        and browser_checks.get("browsing_never_starts_compute") is True,
        "independent_admin_controls": native_checks.get("independent_admin_controls")
        is True,
        "answer_fail_then_success": native_checks.get("answer_failed_job_isolated")
        is True
        and native_checks.get("live_answer_with_validated_citations") is True,
        "index_fail_then_success": native_checks.get("index_failed_job_isolated")
        is True
        and native_checks.get("live_index_persisted") is True,
        "models_reused": native_checks.get("same_process_after_jobs") is True
        and metrics.get("release_id") == manifest["release_id"]
        and all(
            metrics.get("roles", {}).get(role, {}).get("embedding_model_loads") == 1
            and metrics.get("roles", {}).get(role, {}).get("same_worker_as_native_test")
            is True
            for role in ["answer", "index"]
        ),
        "idle_sixty_real_minutes": idle.get("idle_sixty_real_minutes") is True
        and idle.get("real_wall_clock") is True,
        "minute_59_reset": idle.get("minute_59_reset") is True
        and idle.get("minute_59_reset_prevented_old_deadline_stop") is True,
        "native_fargate_sizing": measured_digests == expected_digests
        and len(native.get("tasks", [])) == 2
        and all(
            task.get("cpu") == "1024" and task.get("memory") == "2048"
            for task in native.get("tasks", [])
        ),
        "rollback_smoke": checks["component_rollback_restore"],
        "no_surprise_compute": checks["cleanup_and_workers_zero"]
        and native_checks.get("browsing_workers_zero") is True
        and browser_checks.get("browsing_never_starts_compute") is True,
        "rollback_scope": rollback.get("scope"),
        "evidence": [
            "aws-final-smoke.json",
            "browser-production-smoke.json",
            "aws-idle-verification.json",
            "native-2g-metrics.json",
            "aws-component-rollback.json",
            "deployment-cleanup.json",
        ],
    }
    assert all(
        value is True
        for key, value in smoke.items()
        if key not in {"release_id", "rollback_scope", "evidence"}
    ), "Derived release acceptance is incomplete; quality reference unchanged"
    (art / "aws-release-smoke.json").write_text(json.dumps(smoke, indent=2))
