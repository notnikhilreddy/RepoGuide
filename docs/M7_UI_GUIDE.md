# RepoGuide Milestone 7 — Engineering UI migration guide

## Scope and baseline

This patch was generated against the **original `RepoGuide Copy.zip` after applying your Milestone 6 differential patch**, not an imaginary generic RepoGuide structure. Only new and changed files are included. It does not overwrite your `.env`, `uv.lock`, indexed vectors, historical reports or other unchanged Python modules.

The visual direction is functional, restrained engineering tooling: dark slate surfaces, compact navigation, monospace code labels, mint accents for active work, keyboard-first navigation, simple borders, responsive layouts and reduced-motion support. There are no fake KPI numbers or decorative graph animations.

## Apply and run

1. Commit or back up your current Git state; unzip **outside** the RepoGuide root.
2. `python apply_patch.py --root /absolute/path/to/RepoGuide --dry-run`.
3. Review SHA-256 checks and file list, then run without `--dry-run`.
4. `uv run alembic upgrade head` (adds `source_files` table; no existing tables deleted).
5. `docker compose up -d` to start PostgreSQL/Redis if necessary.
6. `uv run uvicorn repoguide.main:app --reload --host 127.0.0.1` (backend 8000).
7. `cd frontend && npm install && npm run dev` (frontend 5173).
8. Open `http://127.0.0.1:5173`.
9. `npm run typecheck`, `npm run build`, `npm test` inside frontend; `uv run pytest tests/test_ui_jobs.py -v` from root.

If `npm install` fails, retry when the registry is reachable. There is no lockfile in the patch because package downloads were unavailable in the build environment. Commit the generated `frontend/package-lock.json` after installing to make deployment reproducible.

## UI-to-backend contract

| Frontend activity | Endpoint | What it returns |
|---|---|---|
| Repository switcher | GET `/api/ui/repositories` | Indexed repos, SHAs and count summary |
| Overview | GET `/api/ui/repositories/{id}/overview` | Chunk, symbol, edge, dependency and file totals |
| Source tree | GET `/api/ui/repositories/{id}/files` | Exact or partial file paths |
| Monaco source | GET `/api/ui/repositories/{id}/file?path=...` | Exact snapshot or clearly marked chunk reconstruction |
| Symbol outline | GET `/api/ui/repositories/{id}/symbols-in-file?path=...` | Symbols and line ranges |
| Architecture | Existing GET `/repositories/{id}/graph?limit=...` | Stored nodes and edges; now includes location lines |
| Dependencies | Existing GET `/repositories/{id}/dependencies` | Stored declared dependencies |
| Index job | POST `/api/ui/index-jobs`, GET `/api/ui/jobs/{id}` | Real phase updates and resulting repo ID |
| Chat | Existing POST `/repositories/{id}/ask/robust` or `/ask/stream` | Validated final answer with sources, trace ID |
| Feedback | Existing POST `/feedback` | MLflow assessment on trace |
| Evaluation catalog | GET `/api/ui/evaluations` | Allowlisted datasets/reports |
| Evaluation report | GET `/api/ui/evaluations/reports/{name}` | Saved M3 aggregate or per-case data |
| Evaluation run | POST `/api/ui/evaluation-jobs`, GET `/api/ui/jobs/{id}` | Small local benchmark and stored metrics |

No arbitrary file paths, evaluation dataset paths, or GitHub URLs are interpreted directly as filesystem locations. The repository cloning restrictions remain in effect.

### Exact source snapshots

`SourceFile` is a new composite-key table (`repo_id`, `path`, `content`, `byte_count`). The indexer saves exact text from its already-approved size-limited source files and small dependency manifests **within the same indexing transaction** as chunks and symbols. For older indices, the viewer reconstructs available indexed lines and displays a warning. To refresh an older commit, select it under Indexing, check **Reindex this commit**, and submit. Reindexing may regenerate embeddings; the new schema does not migrate old source lines from information that was never stored.

### Honest progress and playback

Index progress is reported at clone → parse → embed batches → DB persist → complete, with real parsed counts. The small graph *adds symbol/chunk nodes only after extraction knows their counts*. It does not simulate per-file completion. Progress is polled every 800 ms from a local worker; in-flight jobs do not survive process restart.

Architecture edges animate only if part of the selected BFS traversal of actual resolved graph relationships. A selected symbol can be opened in Monaco at its recorded start line. The graph is a bounded sample (maximum 1,500 edges), not a claim to render every edge in huge monorepos.

Chat streams LangGraph node completion events; after the routing node selects MCP, the frontend displays a pulsing external tool indicator while the tool step executes. The streamed raw model JSON is **not** displayed as validated Markdown; it is withheld until the final validation event. The Evidence pane allows reordering by recorded fusion, rerank or cosine values (when supplied), and citation clicks jump to the pinned source.

### Evaluation Lab

Existing M3 dict-shaped aggregate reports are visualized as retrieval-method bar charts; M5/M6 row-shaped reports show available case data. The local evaluation worker uses up to 20 cases from an allowlist of datasets. It computes retrieval metrics, logs available MLflow Run metrics/artifacts and uses your instrumented pipeline, producing individual MLflow traces. The UI never invents judge scores. Run CI gates from the M6 scripts separately.

## Architecture and performance

- Vite + React + TypeScript; React Flow for zoomable graph, Monaco read-only code viewer, Recharts for measured evaluation charts, Lucide for small actionable icons, plain CSS custom design tokens.
- GitHub content stays on the server. UI only reads source snapshots stored in PostgreSQL; it never clones repositories or handles secrets.
- Same-origin Vite development proxy avoids broad CORS exposure. The frontend does not store API keys.
- Graph load bounded to 1,500 edges; source files limited by indexer (500 KB per normal source, 150 KB small manifest).
- `prefers-reduced-motion` disables purposeful animations for accessibility. Keyboard: Cmd/Ctrl+K for global navigation; Enter to send questions; Shift+Enter for line breaks.
- Future: virtualize huge file lists, authenticated multi-tenant repository isolation, durable Redis-backed job queue, abortable graph requests and better streaming tokenizer integration.

## What remains before real public hosting

1. **Authn/authz and tenant ownership** on every repository, graph, source-file, evaluation and feedback endpoint.
2. **Safe indexing worker** separated from the FastAPI process: sandbox, network egress restrictions, filesystem/time limits, job cancellation, durable progress updates, quotas.
3. **Security and privacy** for traces, prompts, source code, MCP results and stored snapshots: redaction, retention, per-tenant access controls, deployment secrets.
4. **Static frontend hosting and API gateway** with reverse proxy, HTTPS, CSP, CORS restrictions and websocket/SSE proxy settings.
5. **Real integration verification** on macOS + PostgreSQL, Node installation/build, browsers, live providers and MCP, Redis, MLflow; load/performance and accessibility testing.

## Rollback

The patch script creates `.repoguide_patch_backup_YYYYMMDD_HHMMSS/` containing every modified original and the manifest. Prefer reverting your Git commit; do **not** drop the `source_files` table if you want to retain new snapshots. The optional `uv run alembic downgrade -1` deletes the new snapshot table, so back up database data first.
