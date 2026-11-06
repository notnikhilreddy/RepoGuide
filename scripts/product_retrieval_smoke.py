"""Real CPU/SQL evidence-selection checks in the exact image; zero model API calls."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.update(
    json.loads(Path("/opt/repoguide/release-config.json").read_text())["runtime"]
)
from repoguide.workflow import gather_evidence  # noqa: E402


def main():
    if "host.docker.internal:55432" not in os.environ["DATABASE_URL"]:
        raise ValueError("Isolated database required")
    repo_id = json.loads(Path("/evidence/fixture.json").read_text())["repo_id"]
    cases = [
        (
            "function-tail",
            "How does index_repository persist code chunks and source snapshots atomically?",
            {},
            ["session.commit()", "session.rollback()"],
        ),
        (
            "configuration-definition",
            "Which embedding dimension does EmbeddingService validate and how are vectors normalized?",
            {},
            ["384", "normalize_embeddings=True"],
        ),
        (
            "followup",
            "Which parts of that key separate repositories and model configurations?",
            {
                "history": [
                    {
                        "role": "user",
                        "content": "What is the result_key cache fingerprint used for?",
                    },
                    {
                        "role": "assistant",
                        "content": "It identifies a cached repository answer.",
                        "paths": ["src/repoguide/cache.py"],
                    },
                ]
            },
            ["sha256"],
        ),
    ]
    rows = []
    for name, question, extra, expected in cases:
        state = gather_evidence(
            repo_id=repo_id,
            question=question,
            top_k=8,
            docs_policy="never",
            retrieval_mode="hybrid",
            **extra,
        )
        text = state["repo_context"]
        for term in expected:
            if term not in text:
                raise AssertionError(name + ": missing source evidence " + term)
        if state.get("external_evidence"):
            raise AssertionError("Offline check called external documentation")
        if len(state["sources"]) > 8:
            raise AssertionError("Evidence budget exceeded")
        rows.append(
            {
                "case": name,
                "sources": [
                    {k: s[k] for k in ["file_path", "start_line", "end_line", "origin"]}
                    for s in state["sources"]
                ],
                "context_chars": len(text),
                "passed": True,
            }
        )
        print(json.dumps({"case": name, "passed": True}), flush=True)
    report = {
        "passed": True,
        "real_embeddings_and_reranker": True,
        "live_model_generation": False,
        "database": "isolated PostgreSQL",
        "cases": rows,
    }
    Path("/evidence/product-retrieval-smoke.json").write_text(
        json.dumps(report, indent=2)
    )


if __name__ == "__main__":
    main()
