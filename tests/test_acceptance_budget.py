"""Live smoke spending shares the evaluation ceiling without inventing usage."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from scripts import acceptance_budget


def setup_ledger(tmp_path, monkeypatch, reserved=0):
    monkeypatch.setattr(acceptance_budget, "ROOT", tmp_path)
    (tmp_path / "deployment").mkdir()
    (tmp_path / "deployment/release-config.json").write_text(
        json.dumps(
            {
                "runtime": {
                    "OPENAI_MODEL": "gpt-6-luna",
                    "OPENAI_SERVICE_TIER": "default",
                    "OPENAI_MAX_INPUT_CHARS": "32000",
                    "OPENAI_MAX_OUTPUT_TOKENS": "2000",
                }
            }
        )
    )
    path = tmp_path / ".artifacts/product-eval/spend.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "ceiling_micros": 2000000,
                "reserved_micros": reserved,
                "actual_micros": 123,
                "requests": [{"id": "protected-evaluation"}],
            }
        )
    )
    return path


def test_live_smoke_retains_existing_evaluation_cost_without_fabricating_requests(
    tmp_path, monkeypatch
):
    path = setup_ledger(tmp_path, monkeypatch)
    allocation = acceptance_budget.reserve_answer("production-followup")
    result = json.loads(path.read_text())
    assert result["actual_micros"] == 123
    assert result["requests"] == [{"id": "protected-evaluation"}]
    assert result["acceptance_allocations"][0]["id"] == allocation
    assert result["reserved_micros"] > result["actual_micros"]


def test_parallel_smokes_cannot_both_spend_the_last_allowance(tmp_path, monkeypatch):
    path = setup_ledger(tmp_path, monkeypatch, reserved=1900000)

    def claim(_):
        try:
            acceptance_budget.reserve_answer("parallel-smoke")
            return True
        except RuntimeError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(claim, range(2))) == [False, True]
    result = json.loads(path.read_text())
    assert result["reserved_micros"] <= 2000000
    assert len(result["acceptance_allocations"]) == 1


def test_changed_model_configuration_blocks_before_reservation(tmp_path, monkeypatch):
    path = setup_ledger(tmp_path, monkeypatch)
    config = tmp_path / "deployment/release-config.json"
    value = json.loads(config.read_text())
    value["runtime"]["OPENAI_SERVICE_TIER"] = "priority"
    config.write_text(json.dumps(value))
    before = path.read_bytes()
    with pytest.raises(ValueError):
        acceptance_budget.reserve_answer("unpriced")
    assert path.read_bytes() == before
