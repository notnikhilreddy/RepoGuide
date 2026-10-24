# RepoGuide — unified backend (Milestone 6)

RepoGuide answers questions about versioned GitHub repositories using PostgreSQL/pgvector, Python/JS/TS code parsing, structural relationships, hybrid retrieval, optional read-only MCP tools, and configurable LLM providers. It includes MLflow-compatible observability and an offline evaluation harness.

**This is a backend hardening milestone, not a production security certification.** Public deployment still requires authentication, user/tenant authorization, isolated git workers, rate limiting, secrets management and load/integration tests.

See `docs/M6_MIGRATION.md` for migration and observability instructions.

## Local setup

```bash
uv sync --dev
cp .env.example .env
# Fill .env with local configuration, never commit it
docker compose up -d
uv run alembic upgrade head
# separate terminal: MLflow UI + server
uv run mlflow server --host 127.0.0.1 --port 5000
# separate terminal:
uv run uvicorn repoguide.main:app --reload
```

Browse `/docs` at http://127.0.0.1:8000/docs and MLflow at http://127.0.0.1:5000. `MLFLOW_ENABLED=true` must be set, and the MLflow server must be reachable **before** starting RepoGuide. The trace experiment defaults to `RepoGuide`.

The data schema is unchanged; no new Alembic migration or reindexing is required.

## Endpoints

- `POST /repositories/index`: ingest a public GitHub repository (local dev only)
- `GET /repositories/{repo_id}`: versioned repo metadata
- `POST /repositories/{repo_id}/ask`: backward-compatible response schema
- `POST /repositories/{repo_id}/ask/robust`: structured verified answer, trace ID, metadata
- `POST /repositories/{repo_id}/ask/stream`: SSE (`status`, unverified `draft_delta`, validated `final`)
- `POST /feedback`: attach a human rating to an MLflow trace (local-only until auth)
- `GET /repositories/{repo_id}/symbols`, `/graph`, `/dependencies`: Milestone 2 introspection

## Core invariants

- One evidence graph: retrieve → dependency metadata → model-driven decision → optional read-only MCP.
- One generation: the provider returns one structured draft, which is checked before returning.
- The model may suggest external tools but **cannot** invent arbitrary URLs, dependencies, GitHub repos or tool names.
- Invalid citations are not silently accepted. No evidence → abstain. Partly missing documentation → explicit limitation.
- Cache keys include repository commit and evidence; optional Redis outages do not block responses.
- MLflow logs evidence and timing metadata by default. **Full source code, questions and provider autologging are opt-in** via `.env`, since real repositories may contain sensitive information.

## Evaluation

```bash
uv run pytest tests/test_m6_pure.py tests/test_m6_pipeline.py -q
uv run python evals/benchmark_router_m6.py --providers llm  # needs configured LLM key
uv run python evals/run_m6_mlflow.py REPO_UUID --dataset evals/m3_cases.json --limit 10
uv run python evals/ci_gate.py evals/m6_results.json --min-hit 0.70 --min-mrr 0.45
```

The benchmark data in `evals/` is a starting point. For reliable metrics, verify every expected file and ensure the indexed repo commit matches the evaluation set. LLM judge scoring is **optional**, can incur charges, and needs a supported judge model: pass `--judge-model openai:/gpt-4.1-mini` if credentials are available. Do not interpret these judge scores as ground truth.

## Architecture and limitations

Read [Milestone 6 migration + instrumentation](docs/M6_MIGRATION.md). Previous milestone implementation files are intentionally retired by the patch manifest. Older experimental evaluation results are retained for historical comparisons.

## Milestone 7 — interactive engineering UI

The React/TypeScript frontend lives in [`frontend/`](frontend/README.md), with
architecture exploration, source snapshots/Monaco, live indexing progress,
chat/evidence, dependency browsing, and an Evaluation Lab. Apply the database
migration before first use: `uv run alembic upgrade head`.

Run `uv run uvicorn repoguide.main:app --reload --host 127.0.0.1` in the
project root, then `cd frontend && npm install && npm run dev` in a second
terminal. Open http://127.0.0.1:5173. **Local development only** until the
security and durability steps documented in `docs/M7_UI_GUIDE.md` are completed.
