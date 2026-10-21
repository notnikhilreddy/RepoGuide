"""Generate a small answer sample with citation-syntax checks for human review.

Costs Gemini tokens. This cannot establish whether cited code actually supports
LLM claims. Manually annotate faithfulness and correctness in exported JSONL.
"""

import argparse
import json
import re
from pathlib import Path

from repoguide.db import SessionLocal
from repoguide.rag import answer_question

LABEL = re.compile(r"\[S\d+\]")


def check_citations(answer: str, sources: list[dict]) -> dict:
    allowed = {f"[{s['label']}]" for s in sources}
    used = set(LABEL.findall(answer))
    return {
        "has_citation": bool(used),
        "invalid_labels": sorted(used - allowed),
        "cited_labels": sorted(used),
        # Only syntax/label existence: not proof of factual support.
        "needs_human_grounding_review": True,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("repo_id")
    p.add_argument("--data", default="evals/retrieval.json")
    p.add_argument("--mode", default="hybrid_rerank")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--output", default="evals/m3_answers.jsonl")
    args = p.parse_args()
    if args.limit < 1:
        p.error("--limit must be >=1")
    cases = json.loads(Path(args.data).read_text(encoding="utf-8"))[: args.limit]
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with (
        SessionLocal() as session,
        Path(args.output).open("w", encoding="utf-8") as file,
    ):
        for case in cases:
            result = answer_question(
                session=session,
                repo_id=args.repo_id,
                question=case["question"],
                retrieval_mode=args.mode,
            )
            file.write(
                json.dumps(
                    {
                        "question": case["question"],
                        "expected_paths": case.get("expected_paths", []),
                        **result,
                        "citation_checks": check_citations(
                            result["answer"], result["sources"]
                        ),
                        "human_judgment": {
                            "correct": None,
                            "faithful": None,
                            "comments": "",
                        },
                    }
                )
                + "\n"
            )
    print(f"Saved {len(cases)} generated answers to {args.output}")


if __name__ == "__main__":
    main()
