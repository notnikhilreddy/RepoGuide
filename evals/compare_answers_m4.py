"""Manually review M3 vs M4 answers; Gemini tokens/network required.

uv run python evals/compare_answers_m4.py REPO_ID [limit]
"""
import json
from pathlib import Path
import sys
from time import perf_counter

from repoguide.agent import answer_with_agent
from repoguide.db import SessionLocal
from repoguide.rag import answer_question


def main():
    if len(sys.argv) < 2:
        raise SystemExit('Usage: uv run python evals/compare_answers_m4.py REPO_ID [limit]')
    repo_id = sys.argv[1]
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    cases = json.loads(Path('evals/m4_answer_cases_draft.json').read_text())[:count]
    out = Path('evals/m4_answers.jsonl')
    with out.open('w', encoding='utf-8') as file:
        for case in cases:
            t0 = perf_counter()
            with SessionLocal() as session:
                before = answer_question(
                    session=session, repo_id=repo_id,
                    question=case['question'], retrieval_mode='hybrid',
                )
            m3_latency = perf_counter() - t0
            t1 = perf_counter()
            after = answer_with_agent(
                repo_id=repo_id, question=case['question'], docs_policy='auto',
            )
            m4_latency = perf_counter() - t1
            record = {
                'question': case['question'], 'expected_docs': case['needs_docs'],
                'm3_answer': before['answer'], 'm3_sources': before['sources'],
                'm3_s': round(m3_latency, 3),
                'm4_answer': after['answer'], 'm4_sources': after['sources'],
                'm4_docs_sources': after['docs_sources'], 'm4_trace': after['trace'],
                'm4_s': round(m4_latency, 3),
                'manual_correctness': None, 'manual_faithfulness': None,
                'manual_citation_support': None,
            }
            file.write(json.dumps(record, ensure_ascii=False) + '\n')
            print(case['question'], f'M3 {m3_latency:.1f}s / M4 {m4_latency:.1f}s')
    print('Review:', out)


if __name__ == '__main__':
    main()
