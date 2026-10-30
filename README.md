# RepoGuide

Repository intelligence and grounded codebase Q&A, with a FastAPI backend and a React/TypeScript workspace. RepoGuide indexes versioned GitHub repositories into PostgreSQL/pgvector, parses Python/JavaScript/TypeScript, and combines vector, keyword, and graph retrieval with verified citations and optional read-only MCP documentation tools.

## Local setup

Requirements: Python 3.12+, uv, Docker Compose, and Node.js 20.19+ or 22.12+.

```bash
uv sync --dev --frozen
cp .env.example .env
# Edit .env with local settings and the selected provider's credentials.
docker compose up -d
uv run alembic upgrade head
uv run uvicorn repoguide.main:app --reload --host 127.0.0.1
```

In another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173. API documentation is at http://127.0.0.1:8000/docs.

Redis is optional. MLflow is disabled by default; to enable it, start a reachable tracking server and set `MLFLOW_ENABLED=true` and `MLFLOW_TRACKING_URI` in `.env`. Source content and provider autologging require separate opt-ins.

For a containerized local API, run `docker compose -f compose.yaml -f compose.m8.yaml up --build`. The frontend still runs separately.

## Project layout

| Path | Purpose |
| --- | --- |
| `src/repoguide/` | API, indexing, parsing, retrieval, answer generation, runtime metrics, cloud workers |
| `frontend/` | Repository overview, graph, source explorer, chat, indexing, Evaluation Lab |
| `migrations/` | Ordered Alembic schema history; apply with `alembic upgrade head` |
| `evals/` | Maintained benchmark runners and input datasets; see [evaluation guide](evals/README.md) |
| `tests/` | Offline backend regression tests |
| `scripts/` | SSM configuration, cloud controls, image publishing, MCP smoke checks, reindexing |
| `docker/` | Local API, Lambda, and Fargate images |
| `infra/terraform/` | AWS infrastructure; state and generated plans remain local |
| `docs/` | UI behavior, migration notes, deployment instructions, and cleanup record |

## Deployment settings and SSM

Use **one** private `.env.deploy` for AWS application settings. `.env` remains the separate local development configuration. If creating deployment settings from scratch:

```bash
cp .env.deploy.example .env.deploy
chmod 600 .env.deploy
# Edit .env.deploy, then optionally preview locally:
uv run python scripts/update_runtime_settings.py --dry-run
# Replace the entire SecureString payload with the local file:
uv run python scripts/update_runtime_settings.py
```

The default parameter is `/repoguide/demo/runtime`. Use `--name`, `--profile`, and `--region` to target another environment. Every run writes the complete local file as one SecureString JSON object, including empty values. Keys absent locally are removed from the current payload. The parameter is created automatically if missing; no remote reads, merges, comparisons, or separate delete calls are made. Values are never printed.

Use `KEY=value` lines, optional matching quotes, and full-line comments. Values are literal: no shell expansion, multiline values, or inline comments. For repeated keys, the last line wins. `--dry-run` prepares the replacement locally without contacting AWS. The operator needs `ssm:PutParameter` plus applicable KMS permissions. Use `--kms-key-id` for a custom encryption key; otherwise AWS uses its default SSM key.

Running API/worker processes hydrate SSM settings at startup. Restart workers and recycle existing Lambda execution environments through your deployment process to pick up updated settings; updating SSM alone does not refresh running processes.

See [AWS and Vercel deployment](docs/M8_AWS_VERCEL_BEGINNER_GUIDE.md) for the full deployment workflow.

## Checks

```bash
uv run ruff check src scripts evals tests
uv run ruff format --check src scripts evals tests
DATABASE_URL=postgresql+psycopg://repoguide:repoguide@localhost:5432/repoguide MLFLOW_ENABLED=false uv run pytest -q
cd frontend
npm test
npm run build
```

Backend tests use mocks and temporary files; they do not require a live database, AWS account, model download, or LLM call. Live benchmarks and MCP smoke checks are separate commands and may make external requests or incur provider charges.

## Runtime behavior

- Evidence gathering uses one LangGraph; generation produces one draft followed by citation validation.
- External tool requests are bounded to allowed tools and validated repository/dependency metadata.
- Cache keys include repository commit, evidence, provider, answer depth, and tenant context.
- Local indexing and evaluation jobs run in process; AWS indexing uses SQS/Fargate and durable job status.
- Local API mutations require loopback requests. Cloud mode uses API Gateway JWT claims and admin/budget controls; online evaluations are disabled there.

The hosted demo is not a multi-tenant production deployment. See the [UI guide](docs/M7_UI_GUIDE.md) and deployment guide for operational limitations. Historical [migration notes](docs/M6_MIGRATION.md) remain available; new installations should apply the complete Alembic migration chain.
