# Evaluations

Input datasets and benchmark runners are kept separate from generated results. Result JSON and answer JSONL files are ignored by Git. The UI lists only reports present on disk; a fresh checkout has no saved reports.

| Runner | Purpose |
| --- | --- |
| `benchmark_m3.py` | Retrieval quality and latency across dense, keyword, graph, and hybrid modes |
| `benchmark_m5_live.py` | Full-answer smoke benchmark with citation metadata and manual scoring fields |
| `benchmark_router_m6.py` | Compare bounded LLM/Jev router decisions against `mcp_route_cases.json` |
| `run_m6_mlflow.py` | Full-answer evaluation with MLflow metrics and optional judge scoring |
| `ci_gate.py` | Gate generated full-answer results on measured hit/MRR thresholds |

Run from the project root after indexing a repository:

```bash
# Replaces the old run_retrieval.py / compare_retrieval.py entry points:
uv run python evals/benchmark_m3.py REPO_UUID --data evals/retrieval.json --modes dense graph --top-k 8
# Requires configured LLM and MLflow services:
uv run python evals/run_m6_mlflow.py REPO_UUID --dataset evals/m3_cases.json --limit 10
uv run python evals/ci_gate.py evals/m6_results.json --min-hit 0.70 --min-mrr 0.45
uv run python evals/benchmark_router_m6.py --providers llm
```

`m3_cases.json` and `retrieval.json` are retrieval/answer datasets. `mcp_route_cases.json` is a routing dataset with a different schema and belongs to the router runner, not UI answer evaluation jobs. Runtime metric functions live in `repoguide.evaluation_metrics`, which is included in the installed backend package.

The datasets are historical starter cases. Some expected paths reference files from older RepoGuide commits. Check expected paths against the indexed repository commit before using scores as a quality gate; do not silently replace historical expected paths with guesses.

Live answer/router runners can call LLMs and external tools. Judge scoring is opt-in through `--judge-model` and may incur additional charges. Existing MLflow experiment history is preserved independently of disposable local JSON reports.
