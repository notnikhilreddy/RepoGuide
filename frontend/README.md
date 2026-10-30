# RepoGuide UI — Milestone 7

Professional local engineering workbench for your existing Python RepoGuide API.

## Quick start

Requirements: Node.js 20.19+ or 22.12+, npm, the RepoGuide backend, PostgreSQL and (optional) Redis/MLflow.

From **RepoGuide project root**:

```bash
uv run alembic upgrade head
uv run uvicorn repoguide.main:app --reload --host 127.0.0.1
```

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173. The Vite development proxy forwards `/api`, `/repositories`, and `/feedback` to http://127.0.0.1:8000. No permanent CORS exception or API key in browser code is required.

Check frontend: `npm run build && npm test` (the build includes TypeScript checks).

## Views

- **Overview**: true database counts, repository status, latest commit, languages and exact-snapshot readiness.
- **Indexing**: GitHub URL -> bounded local development background job -> progress phases and real parsed counts; old commits can be refreshed with `force` to store complete code snapshots.
- **Architecture**: React Flow graph of actual parsed symbols and edges. Select symbols, BFS-trace resolved outgoing references, jump to file and line; filter by symbol/type.
- **Code explorer**: file tree, syntax-colored read-only Monaco editor, symbol outline, source-line reveal, commit-pinned GitHub link. Missing source snapshots fall back to **explicitly partial** reconstructed code.
- **Ask**: two-pane conversation and evidence; hybrid retrieval options, external docs policy, response depth, SSE with evidence steps, truthful MCP pulsing, source links, trace ID, feedback.
- **Dependencies**: group and search the declared package inventory with exact manifest links where snapshots exist.
- **Evaluation Lab**: saved metrics, retrieval-mode comparison, case-by-case results, and a small local benchmark worker with MLflow runs/traces.
- **Global search**: Cmd/Ctrl+K navigates pages, repositories and current repository's files.

## Explicit limitations

This is a **local, single-user MVP**; all mutation endpoints are loopback-only and not authenticated. Do not publish the API without authentication, ownership checks, a sandboxed clone worker, a durable job queue, rate limits, and private trace data controls.

The indexer stores exact UTF-8 file snapshots *only for supported, size-limited files*, for **new or forced** indexing. Old source files are reconstructed from chunks and might omit lines. We mark them partial.

In-process job progress does not survive a Python process restart or multiple Uvicorn workers. Indexing progress is based on real stage transitions, not fabricated per-file progress. The UI uses a polling interval for reliability.

The Evaluation Lab may incur LLM calls. It is limited to up to 20 cases from a fixed allowlist of evaluation datasets, and uses local-only job controls. Generated reports appear when present locally; a fresh checkout starts with no historical results.

Full source files/prompts/traces can be sensitive. Continue to use MLflow privacy flags responsibly. The source viewer never evaluates or executes repository code.
