"""Compare dense vs graph retrieval at the same chunk budget."""
import json
import sys
from pathlib import Path

from repoguide.db import SessionLocal
from repoguide.graph import retrieve_with_graph
from repoguide.retriever import retrieve


def first_relevant_rank(paths, expected):
    return next((i for i, path in enumerate(paths, 1) if path in expected), None)


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: uv run python evals/compare_retrieval.py REPO_ID')
    cases = json.loads(Path('evals/retrieval.json').read_text(encoding='utf-8'))
    if not cases:
        raise ValueError('Empty evaluation dataset')
    metrics = {mode: {'hits': 0, 'rr': 0.0} for mode in ('dense', 'graph')}
    with SessionLocal() as session:
        for case in cases:
            dense = retrieve(session=session, repo_id=sys.argv[1], question=case['question'], top_k=8)
            graph = retrieve_with_graph(session=session, repo_id=sys.argv[1], question=case['question'], top_k=8)
            expected = set(case['expected_paths'])
            for mode, chunks in (('dense', dense), ('graph', graph)):
                rank = first_relevant_rank([x.chunk.file_path for x in chunks], expected)
                if rank is not None:
                    metrics[mode]['hits'] += 1
                    metrics[mode]['rr'] += 1 / rank
    for mode, val in metrics.items():
        print(f"{mode}: Hit@8={val['hits']/len(cases):.3f}, MRR@8={val['rr']/len(cases):.3f}")


if __name__ == '__main__':
    main()
