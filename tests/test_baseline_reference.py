"""Protect measured baseline identity when production has an operational repair."""

import copy
import hashlib
import json

import pytest

from scripts.baseline_reference import select_reference


def fixture():
    runtime = {"model": "unchanged-model"}
    configuration = json.dumps(
        {"source_sha256": "measured-source", "runtime": runtime}
    ).encode()
    measured = {
        "release_id": "measured-release",
        "git_sha": "measured-commit",
        "source_sha256": "measured-source",
        "images": {
            "answer": "registry@measured-answer",
            "index": "registry@measured-index",
        },
        "runtime": runtime,
        "quality": {"status": "passed"},
    }
    evaluation = {
        "complete": True,
        "source_sha256": "measured-source",
        "image_id": "measured-answer",
        "release_config_sha256": hashlib.sha256(configuration).hexdigest(),
    }
    production = copy.deepcopy(measured)
    production.update(
        release_id="repaired-release",
        git_sha="repaired-commit",
        source_sha256="repaired-source",
        images={
            "answer": "registry@repaired-answer",
            "index": "registry@repaired-index",
        },
    )
    production["quality"]["deployment_equivalence"] = {
        "verified": True,
        "measured_source_sha256": "measured-source",
        "measured_image_id": "measured-answer",
        "deployment_source_sha256": "repaired-source",
        "deployment_image_ids": {
            "answer": "repaired-answer",
            "index": "repaired-index",
        },
    }
    return production, evaluation, configuration, measured


def test_repaired_release_keeps_original_measurement_and_separate_acceptance():
    production, evaluation, configuration, measured = fixture()
    selected = select_reference(production, evaluation, configuration, measured)
    assert selected["source_sha256"] == "measured-source"
    assert selected["images"]["answer"] == "registry@measured-answer"
    assert selected["git_sha"] == "measured-commit"
    assert selected["production_acceptance"]["release_id"] == "repaired-release"
    assert "production_acceptance" not in measured


@pytest.mark.parametrize(
    "change", ["unmeasured", "image", "config", "proof", "runtime"]
)
def test_mismatched_quality_reference_cannot_be_approved(change):
    production, evaluation, configuration, measured = fixture()
    if change == "unmeasured":
        measured = None
    elif change == "image":
        measured["images"]["answer"] = "registry@different-image"
    elif change == "config":
        configuration += b" "
    elif change == "proof":
        production["quality"]["deployment_equivalence"]["verified"] = False
    else:
        production["runtime"]["model"] = "changed-model"
    with pytest.raises(ValueError):
        select_reference(production, evaluation, configuration, measured)


def test_directly_measured_release_can_be_approved_without_equivalence():
    _, evaluation, configuration, measured = fixture()
    selected = select_reference(measured, evaluation, configuration)
    assert selected["production_acceptance"]["release_id"] == "measured-release"
