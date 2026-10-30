# RepoGuide Milestone 6 — migration, observability, evaluation

This file accompanies a **patch**, not a fresh project. It was produced by inspecting the attached RepoGuide ZIP. It uses your existing `src/repoguide/` package and preserves the PostgreSQL schema.

## 1. Install safely

1. Make a Git commit or a copy of your current project. Do not copy your `.venv`, `.env`, database volumes, or tokens into a patch backup.
2. Extract the patch ZIP outside the project. Run `python apply_patch.py --root /path/to/RepoGuide --dry-run` and review changed/deleted paths. The patch validates original file hashes and refuses to overwrite divergent originals.
3. Run `python apply_patch.py --root /path/to/RepoGuide`. It saves changed originals under `.repoguide_patch_backup_.../` and applies only listed files. To roll back, restore the backup or `git checkout` the commit; see patch README.
4. Run `uv lock && uv sync --dev` in the project root to regenerate `uv.lock` after adding MLflow. The patch leaves your old lockfile alone because its content must be resolved by uv in your actual environment.
5. Copy new `.env.example` fields into your existing `.env` (the patch never overwrites `.env`).
6. Start `docker compose up -d`, then `uv run mlflow server --host 127.0.0.1 --port 5000` in a separate terminal, then `uv run uvicorn repoguide.main:app --reload`.
7. Validate `/health`, `/docs`, a known repository ID, the robust endpoint and the Traces tab.

**No Alembic migration or forced reindexing is necessary.** This patch relies on the Milestone 2/3 tables already created.

## 2. What was consolidated

| Before | After |
|---|---|
| `rag.py`, `agent.py`, `agent_v2.py`, `robust_v2.py` | `workflow.py` gathers evidence; `pipeline.py` generates and validates once |
| `routing_v2.py`, `docs_catalog.py` keyword heuristics | `router.py` uses Jev (optional) or dedicated structured-output LLM |
| `provider_v2.py` | `provider.py`, reusing your existing `llm.py` provider clients |
| `answers_v2.py` | `answers.py`, separate user-facing Markdown and auditable claims |
| `cache_v2.py` | `cache.py`, with final-answer and short-lived Context7 caches |
| `robust_api_v2.py` | `api.py`, same engine for robust/streamed responses plus feedback |
| `main.py` branching into different answer implementations | `main.py` delegates to the common pipeline |

Retired legacy tests/scripts that only exercised deleted implementations are removed. Your parser, indexer, vector retriever, graph retriever, hybrid search, Tree-sitter analyzer, and existing `llm.py` providers are preserved and instrumented. Your old evaluation datasets and previous result artifacts are **not deleted**.

## 3. Jev / model-based tool routing

The router receives the question, top indexed source paths/symbols, and declared dependencies. It returns a validated `RouteDecision` with `intent`, `sufficient`, `tools`, `dependencies`, reason and optional confidence. `ROUTER_PROVIDER=llm` (default) invokes a dedicated minimal-JSON classification prompt through your selected provider, independent of the normal answer prompt. `ROUTER_PROVIDER=jev` calls the official Jev `POST /v1/systemone` endpoint using `JEV_API_KEY`; configure `JEV_ENDPOINT=https://jevtypesafeai.com/api/v1/decide` **only if using that hosted gateway's key**. On Jev failure it falls back to the configured LLM router. If all routing fails, it selects no external tools rather than fabricating arguments.

An external call can only use an allowlisted tool (`context7` or `github`). Context7 library arguments must match manifest-declared packages; GitHub tools are limited to the exact indexed repository and read-only resources. `docs_policy=never` overrides the model. Jev probabilities are **not assumed calibrated for your dataset**: evaluate their false-negative rates and latency with `evals/benchmark_router_m6.py`.

**Remaining precision limitation:** Jev classification and dependency detection are separate. Jev cannot invent a new package string; if the declared package is not mentioned, the Context7 call may be skipped. This is safer than guessing arbitrary package IDs, but it is not a complete universal documentation retrieval engine.

## 4. MLflow: what lands where

Start MLflow **before** Uvicorn, then execute one request and navigate to experiment `RepoGuide`.

| UI | What appears | How recorded |
|---|---|---|
| **Traces** | Request, graph, vector/keyword/graph search, fusion, context packing, router, MCP, SQL, embedding, generation, citation validation, Redis cache, timing and exceptions | Nested `mlflow.start_span()` spans through `telemetry.py`, plus optional SDK autolog |
| **Traces → span attributes** | Model, provider, local/tool choice, retrieval rank and distance arrays, counts, status, timing, token counts when provider exposes them | `record(..., attr=value)` and model usage metadata |
| **Traces → inputs/outputs** | Sanitized payload summaries by default. Complete prompts, chunks and response bodies if explicitly enabled | `MLFLOW_CAPTURE_CONTENT` and optional `MLFLOW_AUTOLOG` |
| **Runs** | Dataset/config parameters, Hit@8, FileRecall@8, MRR@8, citation validity, latency statistics, evaluation JSON artifacts, and CPU/memory/network/disk system metrics | `evals/run_m6_mlflow.py` using `mlflow.start_run(log_system_metrics=True)`, `psutil`, and `log_metric` |
| **Assessments / Feedback** | User ratings, code checks, and offline LLM judges | `mlflow.log_feedback` or `mlflow.genai.evaluate()` |

### Full trace capture opt-in

```
MLFLOW_ENABLED=true
MLFLOW_TRACKING_URI=http://127.0.0.1:5000
MLFLOW_EXPERIMENT=RepoGuide
MLFLOW_CAPTURE_CONTENT=true
MLFLOW_AUTOLOG=true
```

This logs untrusted source excerpts, prompts, tool responses, and answers where the instrumentation and SDK provide them. **Only enable this for a local development repository that contains no secrets, private data, or unauthorized content.** MLflow prompt capture isn't an authorization mechanism, and it is not safe to send other tenants' private code to a shared tracing server without access control. Turn both content flags off in public deployments and configure redaction, sampling, retention, and secure storage first.

OpenAI-compatible `responses.create()` and Google GenAI may expose provider-reported token usage; the explicit instrumentation captures it when available. Optional MLflow provider autologging enriches SDK-specific detail. Ollama/Gateway usage may be missing or zero; no token or USD cost is fabricated. Call-graph spans reflect instrumented application functions, not every Python interpreter operation.

`mlflow.log_metric()` is associated with a **Run**, not a Trace. If metrics appear under Runs and not Traces, that is expected. Span attributes describe per-request metrics in the trace timeline. To view populated Traces, actually call `/ask` after telemetry starts.

### Database + ordinary code tracing

The patch instruments SQLAlchemy's before/after/error cursor hooks, wrapping DB operations in `db.sql` spans, with SQL statement fingerprints and row counts (not bound values). `index.repository`, parser, symbol analyzer, embeddings, vector/keyword/graph/RRF/reranking, context packing and Git/MCP operations are also traced. Parent-child nesting lets you diagnose latency and failure stage. DB instrumentation may add overhead at high QPS; sampling and selective SQL spans should be tuned during deployment.

### Redis and model output visibility

`cache.lookup` / `cache.store` spans expose hit/miss and timing. Context7 documentation results have short-lived Redis caching; final validated answers have a configurable TTL. Redis failure is nonfatal. Streaming emits provisional raw deltas and a validated final event; only the **final** response should be rendered as authoritative by your future UI.

## 5. Metrics and gold examples

Version the questions with their commit SHA. The old `evals/m3_cases.json` is useful for getting started but should be reviewed against the indexed repository before serious comparisons. The evaluator writes `evals/m6_results.json` locally, logs aggregate metrics to an MLflow Run, attaches raw row results as an artifact, and stores MLflow trace IDs for each row. For a model-based groundedness/relevance check, pass `--judge-model PROVIDER:/MODEL` with valid judge credentials; this uses the supported `mlflow.genai.evaluate` API on existing traces, so it doesn't re-run RepoGuide generation.

For a measured CI gate: `uv run python evals/ci_gate.py evals/m6_results.json --min-hit 0.70 --min-mrr 0.45`. The sample thresholds are **illustrative**; set them from measured baseline runs, not arbitrary optimism. `.github/workflows/quality.yml` runs fast deterministic tests on PRs. `.github/workflows/evaluation.yml` is explicitly triggered on a self-hosted runner with an existing indexed DB snapshot and model cache; without these the workflow must fail instead of reporting success.

## 6. Tracing privacy and completeness limitations

- Never log API keys, passwords or arbitrary database parameter values. `safe()` redacts recognizable credentials and bounds serialized output sizes, but automated redaction cannot guarantee removal of every private secret in arbitrary code.
- Trace *inputs and outputs* are sanitized summaries by default. Opt in to content-level diagnostics when authorized.
- The built-in citation verifier only validates label membership; it **does not prove that the code entails the claim**. Offline retrieval-groundedness judges are supplemental and require manual calibration.
- Structured-answer parsing is not foolproof. If invalid, it abstains without silently issuing an additional paid completion. LLM provider failures can still raise errors; production error handling requires more integration tests.
- The existing Git clone endpoint is **not safe for anonymous internet exposure** without sandboxed workers and operational limits.
- Human feedback is local development-only until authentication and trace ownership are enforced. Do **not** enable `/feedback` publicly in its current form.
- Different provider APIs expose different usage and streaming details; some token, cache and spend fields may legitimately be absent. "Every possible MLflow capability" cannot be guaranteed by a single SDK integration; these are explicit instrumentation points with selective autologging.

## 7. Quick verification

```bash
uv run python -m compileall src/repoguide
uv run pytest tests/test_answer_validation.py tests/test_pipeline.py -q
uv run pytest -q                 # Full suite needs all original dependencies
uv run python evals/benchmark_router_m6.py --providers llm
uv run python evals/run_m6_mlflow.py REPO_UUID --dataset evals/m3_cases.json --limit 5
```

Example request:

```json
{"question":"How does a repository indexing request reach the database?","top_k":8,"docs_policy":"auto","retrieval_mode":"hybrid","answer_depth":"detailed"}
```

Send to `/repositories/{repo_id}/ask/robust`, inspect `trace_id`, follow that trace in MLflow, and confirm child spans, output and user feedback. For a streaming smoke test call `/repositories/{repo_id}/ask/stream` using `curl -N`. Avoid claiming it is production-ready until your providers, MCP server, Redis and Postgres are validated on the target environment.
