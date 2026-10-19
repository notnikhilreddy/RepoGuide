import json
import sys
from pathlib import Path

from repoguide.db import SessionLocal
from repoguide.retriever import retrieve


def main():
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: uv run python evals/run_retrieval.py REPO_ID"
        )

    repo_id = sys.argv[1]

    cases = json.loads(
        Path("evals/retrieval.json").read_text(
            encoding="utf-8"
        )
    )

    if not cases:
        raise ValueError("Evaluation dataset is empty")

    hits_at_1 = 0
    hits_at_5 = 0
    reciprocal_rank_sum = 0.0

    with SessionLocal() as session:
        for case in cases:
            results = retrieve(
                session=session,
                repo_id=repo_id,
                question=case["question"],
                top_k=5,
            )

            paths = [
                result.chunk.file_path
                for result in results
            ]

            expected = set(case["expected_paths"])

            rank = next(
                (
                    i for i, path in enumerate(paths, start=1)
                    if path in expected
                ),
                None,
            )

            if rank == 1:
                hits_at_1 += 1

            if rank is not None:
                hits_at_5 += 1
                reciprocal_rank_sum += 1 / rank

            print(f"\nQuestion: {case['question']}")
            print(f"Expected: {sorted(expected)}")
            print(f"Retrieved: {paths}")
            print(f"First relevant rank: {rank}")

    total = len(cases)

    print("\n--- Retrieval baseline ---")
    print(f"Hit@1: {hits_at_1 / total:.3f}")
    print(f"Hit@5: {hits_at_5 / total:.3f}")
    print(f"MRR@5: {reciprocal_rank_sum / total:.3f}")


if __name__ == "__main__":
    main()