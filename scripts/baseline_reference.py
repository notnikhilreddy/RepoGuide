"""Keep a protected quality reference bound to the bytes actually measured."""

from __future__ import annotations

import copy
import hashlib
import json


def select_reference(production, evaluation, configuration, measured=None):
    """An operational repair may reference its original, measured AI release.

    The original manifest is preserved, including its Git/source/image identity.
    Production acceptance is separate metadata, never a new measurement claim.
    Call only after the publisher validates quality and real deployment evidence.
    """
    if production.get("quality", {}).get("status") != "passed":
        raise ValueError("A passing measured release authorization is required")
    reference = copy.deepcopy(measured if measured is not None else production)
    config = json.loads(configuration)
    if (
        evaluation.get("complete") is not True
        or reference.get("quality", {}).get("status") != "passed"
        or reference.get("source_sha256") != evaluation.get("source_sha256")
        or reference.get("images", {}).get("answer", "").split("@")[-1]
        != evaluation.get("image_id")
        or config.get("source_sha256") != evaluation.get("source_sha256")
        or reference.get("runtime") != config.get("runtime")
        or hashlib.sha256(configuration).hexdigest()
        != evaluation.get("release_config_sha256")
    ):
        raise ValueError(
            "Quality reference differs from the measured source/image/config"
        )
    if measured is not None:
        proof = production["quality"].get("deployment_equivalence", {})
        if (
            proof.get("verified") is not True
            or proof.get("measured_source_sha256") != reference["source_sha256"]
            or proof.get("measured_image_id") != evaluation["image_id"]
            or proof.get("deployment_source_sha256") != production["source_sha256"]
            or proof.get("deployment_image_ids")
            != {k: v.split("@")[-1] for k, v in production["images"].items()}
            or production["runtime"] != reference["runtime"]
        ):
            raise ValueError("No verified equivalence to the measured reference")
    reference["production_acceptance"] = {
        "release_id": production["release_id"],
        "source_sha256": production["source_sha256"],
        "images": production["images"],
        "quality_acceptance": production["quality"].get("acceptance"),
        "deployment_equivalence": production["quality"].get("deployment_equivalence"),
        "scope": "The quality report describes this reference's measured bytes; production functional evidence describes the separately identified deployment.",
    }
    return reference
