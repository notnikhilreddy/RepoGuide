"""Deterministic, offline docs-routing evaluation. No database or Gemini requests."""
import json
from pathlib import Path
from repoguide.docs_catalog import choose_docs, should_use_docs

cases = json.loads(Path('evals/m4_route_cases.json').read_text())
correct = 0
for case in cases:
    found = choose_docs(case['question'])
    predicted = should_use_docs(case['question'], 'auto', found)
    if predicted == case['expects_docs']:
        if not predicted or (case['library'], case['topic']) in {(d.library, d.topic) for d in found}:
            correct += 1
    print('✓' if predicted == case['expects_docs'] else '✗', case['question'])
print(f'Policy-match accuracy: {correct}/{len(cases)} (hand-authored local examples)')
