"""Measure offline readiness and repeated inference inside a constrained image."""

import json
import os
import resource
import statistics
import sys
import time
from pathlib import Path

from repoguide.cloud_worker import warmup
from repoguide.embeddings import get_embedding_service

kind, allocation = sys.argv[1:]
t = time.monotonic()
warmup(kind)
ready = time.monotonic() - t
samples = []
for _ in range(5):
    start = time.monotonic()
    assert (
        len(
            get_embedding_service().encode_query(
                "How does indexing commit repository data?"
            )
        )
        == 384
    )
    if kind == "answer":
        from repoguide.reranker import get_reranker

        get_reranker().predict(
            [
                (
                    "database commit",
                    "The indexing transaction commits code chunks and snapshots.",
                )
            ]
        )
    samples.append(time.monotonic() - start)
report = {
    "kind": kind,
    "allocation": allocation,
    "platform": "linux/amd64 under Apple Silicon emulation",
    "ready_seconds": ready,
    "warm_inference_p50_seconds": statistics.median(samples),
    "warm_inference_p95_seconds": max(samples),
    "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
    "cuda_visible": bool(os.getenv("CUDA_VISIBLE_DEVICES")),
}
Path("/evidence/benchmark-" + kind + "-" + allocation + ".json").write_text(
    json.dumps(report, indent=2)
)
print(json.dumps(report))
