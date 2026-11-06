> Historical initial-release record. The current improvement release, authorization, scope and verification status are tracked in [product-release.md](product-release.md) and [IMPROVEMENT_STATUS.md](../IMPROVEMENT_STATUS.md). The earlier evaluation/idle deferrals do not authorize a new skipped quality gate.

# Deployment handoff

**Status: AWS deployed and the existing Vercel domain promoted.** The owner resumed deployment on November 5, 2026 with OpenAI and explicitly skipped paid comparative evaluation. The owner also stopped the long idle verification after about 15 minutes and will verify that later; no live 60-minute/reset success is claimed. See [the scoped exception](owner-authorized-release.md). Evaluation is marked skipped, never passed; no approved quality baseline has been invented.

Read `audit.md`, `release-evidence.md`, `sizing.md`, `cost-estimate.md` and `runbooks.md` before resuming. The approved initial reference is commit `4aa70f5`; the existing Neon, Upstash and Vercel resources must be preserved. The administrator email is `nikhilreddy.maligireddy2@gmail.com`. GitHub MCP is intentionally disabled.

Final local validation passed 135 backend tests, four frontend Node tests and four browser tests, plus both exact-image worker contracts and the extracted API ZIP against disposable TLS PostgreSQL. Hosted AWS/Cognito/OpenAI/browser results are recorded separately in `release-evidence.md`; fixtures do not establish live acceptance or comparative quality.

Answer generation uses `gpt-6-luna`, standard service tier, low reasoning effort, at most 2,000 output tokens and a 32,000-character full-request ceiling. Repository evidence packing is bounded to 12,000 characters. The existing Vercel project, Neon production database and Upstash are reused. Both CPU workers use 1 vCPU / 2 GiB, selected from local and native measurements, with desired count zero by default.

## Local checks

```bash
uv sync --dev --frozen
uv run ruff check src scripts evals tests
uv run ruff format --check src scripts evals tests
uv run pytest -q
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
npx --prefix frontend playwright install chromium
npm --prefix frontend run test:e2e
uv run python scripts/package_cloud.py
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform validate
```

The browser suite uses an HTTP fixture, not AWS/Cognito. The worker harness uses real CPU models, Git cloning, PostgreSQL and validation with Moto's AWS transports; Answer generation is explicitly a fixture while live requests are paused. The disposable validation database is on localhost port 55432, separate from development and production.

## Build artifacts

```bash
uv run python scripts/prepare_release.py
docker buildx build --platform linux/amd64 --provenance=false --load \
  -f docker/Dockerfile.answer -t repoguide-answer:candidate .
docker buildx build --platform linux/amd64 --provenance=false --load \
  -f docker/Dockerfile.index -t repoguide-index:candidate .
uv run python scripts/package_cloud.py
```

Requirements are split and hash-locked under `deployment/`. Base images and model revisions are pinned. Workers contain only their role's application modules and required CPU dependencies, with preloaded offline weights. Tasks run as UID/GID 10001, drop all Linux capabilities and use a read-only root with an owned writable `/tmp` volume. The old Lambda/worker Dockerfiles are retired. API/controller ZIPs contain only their small modules and the API's Linux psycopg wheel.

`reports/` and `.artifacts/` are ignored. `.artifacts/private/` contains the database backup and raw provider/project audit data; do not publish it. No credentials belong in a plan, Terraform variables/state, image, frontend bundle or Git history.

## Release discipline

Only resume paid comparative evaluation after the owner requests it. The pause marker remains deliberate. The initial deployment exception binds exact source, configuration, package and image identities and retains all technical/security checks. Changed artifacts fail verification. Future releases retain the paired evaluated path; baseline promotion explicitly rejects skipped evaluation. Offline scores and fixtures cannot fabricate a passing quality gate.

The legacy GitHub publisher has been disabled remotely and retired in source. Vercel Git auto-deploy is disabled in the deployed configuration. Source changes remain uncommitted and unpushed; local workflow files are not evidence that CI ran. Preserve Terraform state and external databases; do not destroy the stack as a troubleshooting step. Initial Cognito administrator credentials and the tested Neon backup are private files under `.artifacts/private/`.
