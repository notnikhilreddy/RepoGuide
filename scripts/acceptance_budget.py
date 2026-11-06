"""Reserve a conservative live-smoke allowance in the shared $2 model ledger.

This records an allocation, not invented provider requests or actual usage.
Each accepted answer can make one router and one generator call on each of
three worker attempts. At frozen 32,000 input characters and 2,000 output
tokens, $0.015 per call bounds the verified default-tier model price.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evals.cost_budget import SpendingLedger  # noqa: E402


def reserve_answer(purpose):
    runtime = json.loads((ROOT / "deployment/release-config.json").read_text())[
        "runtime"
    ]
    if (
        runtime["OPENAI_MODEL"] != "gpt-6-luna"
        or runtime["OPENAI_SERVICE_TIER"] != "default"
        or int(runtime["OPENAI_MAX_INPUT_CHARS"]) > 32000
        or int(runtime["OPENAI_MAX_OUTPUT_TOKENS"]) > 2000
    ):
        raise ValueError("Live acceptance allocation does not cover this configuration")
    amount = 6 * 15000
    allocation = {
        "id": uuid.uuid4().hex,
        "purpose": purpose,
        "time": int(time.time()),
        "maximum_provider_calls": 6,
        "reserved_micros": amount,
        "status": "held_upper_bound_not_actual_usage",
    }
    with SpendingLedger(ROOT / ".artifacts/product-eval/spend.json").locked() as ledger:
        if (
            ledger["ceiling_micros"] > 2000000
            or ledger["reserved_micros"] + amount > ledger["ceiling_micros"]
        ):
            raise RuntimeError("The total $2 model acceptance budget is exhausted")
        ledger["reserved_micros"] += amount
        ledger.setdefault("acceptance_allocations", []).append(allocation)
    return allocation["id"]


if __name__ == "__main__":
    print(reserve_answer(sys.argv[1]))
