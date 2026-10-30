"""Gate on measured deterministic retrieval metrics, not subjective judges."""

import argparse
import json
import sys
from pathlib import Path


def check(path: str, min_hit: float, min_mrr: float):
    rows = json.loads(Path(path).read_text())
    if not rows:
        raise ValueError("Evaluation results are empty")
    hit = sum(r["hit_at_8"] for r in rows) / len(rows)
    mrr = sum(r["mrr_at_8"] for r in rows) / len(rows)
    return {
        "hit_at_8": hit,
        "mrr_at_8": mrr,
        "passed": hit >= min_hit and mrr >= min_mrr,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("results")
    p.add_argument("--min-hit", type=float, required=True)
    p.add_argument("--min-mrr", type=float, required=True)
    a = p.parse_args()
    result = check(a.results, a.min_hit, a.min_mrr)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["passed"] else 1)
