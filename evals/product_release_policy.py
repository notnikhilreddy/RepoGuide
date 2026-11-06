"""Apply an explicit release-scoped acceptance of measured quality tradeoffs.

The strict comparison remains intact. Missing/invalid measurements and safety
failures still raise before this policy is considered; accepted regressions and
overlapping observed ranges remain visible in the release evidence.
"""

from __future__ import annotations

import hashlib
import json

from evals.release_gate import compare


def measured_comparison(baseline, candidate, policy=None):
    result = compare(baseline, candidate)
    if result["passed"] or policy is None:
        return result
    if (
        policy.get("version") != "product-owner-tradeoffs-v1"
        or policy.get("source_sha256") != candidate["source_sha256"]
        or policy.get("baseline_source_sha256") != baseline["source_sha256"]
        or policy.get("candidate_report_sha256")
        != hashlib.sha256(json.dumps(candidate, sort_keys=True).encode()).hexdigest()
        or policy.get("accept_overlapping_observed_ranges") is not True
    ):
        raise ValueError("Measured quality acceptance does not bind this exact release")
    allowed = policy.get("accepted_slice_regressions", [])
    if sorted(result["regressions"], key=lambda r: (r["group"], r["metric"])) != sorted(
        allowed, key=lambda r: (r["group"], r["metric"])
    ):
        raise ValueError(
            "Unreviewed quality regression; owner acceptance does not apply"
        )
    if any(
        row["group"] != "slices/provenance"
        and row["group"] != "slices/grounding"
        or row["metric"]
        not in {"relevance", "citation_precision", "supported_claim_precision"}
        or row["baseline"] - row["candidate"] > 0.125
        for row in allowed
    ):
        raise ValueError("Owner tradeoff exceeds the reviewed minor slice differences")
    return {
        **result,
        "passed": True,
        "strict_non_regression_passed": False,
        "acceptance": "owner_accepted_measured_tradeoffs",
        "authorization": policy["authorization"],
    }
