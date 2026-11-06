"""Cross-process hard reservation ledger for the owner-approved $2 evaluation.

No prompts, credentials or answers are written here. UTF-8 bytes bound input
characters conservatively; failed/unknown requests retain their reservation.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class SpendingLedger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def locked(self):
        with self.path.with_suffix(".lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            value = (
                json.loads(self.path.read_text())
                if self.path.exists()
                else {
                    "ceiling_micros": 2000000,
                    "reserved_micros": 0,
                    "actual_micros": 0,
                    "requests": [],
                }
            )
            try:
                yield value
            finally:
                temporary = self.path.with_suffix(".tmp")
                temporary.write_text(json.dumps(value, indent=2))
                temporary.replace(self.path)
                fcntl.flock(lock, fcntl.LOCK_UN)

    def reserve(self, request):
        if (
            request.get("model") != "gpt-6-luna"
            or request.get("service_tier", "default") != "default"
        ):
            raise ValueError("No verified evaluation price for this model/tier")
        input_bound = len(json.dumps(request, ensure_ascii=False).encode())
        if input_bound > 250000:
            raise ValueError(
                "Evaluation input exceeds the verified short-context pricing range"
            )
        amount = math.ceil(
            input_bound * 0.10 + int(request["max_output_tokens"]) * 0.50
        )
        request_id = uuid.uuid4().hex
        with self.locked() as ledger:
            if (
                ledger["ceiling_micros"] > 2000000
                or ledger["reserved_micros"] + amount > ledger["ceiling_micros"]
            ):
                raise RuntimeError("The total $2 evaluation budget is exhausted")
            ledger["reserved_micros"] += amount
            ledger["requests"].append(
                {
                    "id": request_id,
                    "reserved_micros": amount,
                    "time": int(time.time()),
                    "status": "reserved",
                }
            )
        return request_id

    def complete(self, request_id, usage):
        tokens_in = int(getattr(usage, "input_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "output_tokens", 0) or 0)
        cached = int(
            getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", 0)
            or 0
        )
        amount = math.ceil(
            max(0, tokens_in - cached) * 0.10 + cached * 0.01 + tokens_out * 0.50
        )
        with self.locked() as ledger:
            row = next(x for x in ledger["requests"] if x["id"] == request_id)
            if row["status"] == "complete":
                return
            if amount > row["reserved_micros"]:
                raise RuntimeError(
                    "Provider usage exceeded the conservative reservation; stop evaluation"
                )
            ledger["actual_micros"] += amount
            row.update(
                status="complete",
                input_tokens=tokens_in,
                output_tokens=tokens_out,
                actual_micros=amount,
            )


def ledger():
    path = os.getenv("REPOGUIDE_EVAL_BUDGET_FILE")
    if not path:
        raise RuntimeError(
            "A shared evaluation spend ledger is required before live calls"
        )
    return SpendingLedger(path)
