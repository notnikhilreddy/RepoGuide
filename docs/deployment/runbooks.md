> Historical initial-release record. The current improvement release, authorization, scope and verification status are tracked in [product-release.md](product-release.md) and [IMPROVEMENT_STATUS.md](../IMPROVEMENT_STATUS.md). The earlier evaluation/idle deferrals do not authorize a new skipped quality gate.

# Runbooks

## Current release and operating controls

AWS is deployed in Ohio using profile `repoguide`. The owner resumed rollout with OpenAI and explicitly skipped paid comparative evaluation for the exact initial release. `.artifacts/live-evaluation-paused` remains present; do not remove it or run paid evaluation automatically. See `owner-authorized-release.md` and `release-evidence.md` for the truthful acceptance status.

The existing frontend is https://repo-guide-five.vercel.app. Sign in through Cognito using `nikhilreddy.maligireddy2@gmail.com`; the initial password is stored privately in `.artifacts/private/cognito-admin.json`. Only `repoguide-admins` can Start/Stop workers. No invitation email was sent. Use the UI's independent Answer/Indexer controls: Start, wait for **ready**, submit work, then Drain & stop. Ordinary browsing works at zero compute. Stop after work to avoid paying for an additional idle hour.

For an authenticated AWS operator, the CLI uses the same durable state machine:

```bash
uv run python scripts/cloud_control.py status answer
uv run python scripts/cloud_control.py status index
uv run python scripts/cloud_control.py start answer
uv run python scripts/cloud_control.py stop answer
# Only when interruption is intended:
uv run python scripts/cloud_control.py stop answer --force
```

A worker is genuinely ready only after database/model/warm-up checks. ECS RUNNING alone is insufficient. Browser/status reads do not reset the idle timer; accepted jobs and job completion do. Queue traffic cannot enable an off worker. Do not use direct `ecs update-service --desired-count 1` for normal operation because it bypasses the control ledger.

## Local development and validation

Use Python 3.12+, uv, Docker Desktop/buildx, Node 24+ and Chromium. Keep local settings in `.env` and deployment secrets in `.env.deploy`, mode 600. The provider is `openai` with `OPENAI_API_KEY` and `OPENAI_MODEL=gpt-6-luna`; never add a key to a `VITE_` variable.

```bash
uv sync --dev --frozen
uv run uvicorn repoguide.main:app --reload
# In a second terminal:
npm --prefix frontend ci
npm --prefix frontend run dev
```

Vite runs on localhost:5173 and proxies API paths to localhost:8000. `npm run build` compiles static assets; it does not start a development server. For a startup-only probe, disabling MLflow in that process avoids depending on a local tracking service; deployment already keeps MLflow disabled.

The disposable validation PostgreSQL container is `repoguide-validation`, localhost **55432**, database/user/password `repoguide`. These are test credentials only. Existing development containers and production Neon must not be removed. Seed helpers reject non-local URLs. Use the pinned approved reference commit `4aa70f5` and corpus under `evals/`.

```bash
uv run moto_server -H 127.0.0.1 -p 5500
# In another terminal, sequentially:
uv run python scripts/local_worker_smoke.py index
uv run python scripts/local_worker_smoke.py answer
docker run --rm --platform linux/amd64 --memory 512m \
  -v "$PWD/deployment:/deployment:ro" -v "$PWD/scripts:/scripts:ro" \
  -v "$PWD/.artifacts:/evidence" repoguide-answer:candidate \
  python /scripts/packaged_read_smoke.py
```

Worker contracts use real CPU models, clone/parser/database work and Moto AWS transports. Answer generation in this harness is explicitly a mounted fixture and is not copied into production. Offline browser tests use HTTP fixtures. Neither is a live quality evaluation. Use README for formatting, tests and image build commands. Do not rebuild an image after recording its exact-image scan/contract evidence.

## Configuration, secrets and data preservation

Run `terraform -chdir=infra/terraform output -json` to obtain current IDs. Keep `frontend_origin` fixed to the existing Vercel URL. State and ignored `deployed.auto.tfvars.json` are operational assets; preserve a private backup, do not restore the historical destroyed-resource state. Images are pinned by digest, not `latest`.

Neon is authoritative for all repository data. API and Answer use a SELECT-only login; Index uses a separate login with CRUD on the six repository tables only. Neither receives the Neon owner URL. Role creation and SSM updates use `scripts/configure_cloud_secrets.py`; it deliberately refuses an already-existing role. On this stack, reuse the existing SSM scopes rather than rerunning a fresh-install helper blindly. Secret rotation should preserve role isolation and restart workers/recycle Lambda so startup-loaded credentials refresh. Frozen model/prompt settings come from the release manifest, not mutable SSM overrides.

Take a new private custom-format database backup and **restore-test it locally** before migrations, role changes or rollback involving data. The rollout's tested backup is `.artifacts/private/neon-before-openai.dump`. Existing RepoGuide row fingerprints are recorded before/after acceptance. Indexing smoke uses a separate public MarkupSafe repository; never force-reindex the owner's data as a health check. No production schema migration was needed.

S3 is private/encrypted/versioned, Upstash is optional cache, and DynamoDB/SQS are job/control transports. Missing cache means a normal miss. Context7 hosted HTTP MCP is enabled; GitHub MCP remains unavailable by owner choice. Missing external evidence must produce a partial/insufficient result, not invented issues or documentation.

## Future releases and evaluation

The current owner exception binds source/config/package/images and records `evaluation_passed=false`. It cannot advance an approved quality baseline. Changed source/config/images fail release verification. The old ungated GitHub publisher remains disabled; main/environment protections are applied. Source remains uncommitted/unpushed, and no CI success is claimed. Paid evaluation is manual only; no automatic paid deployment workflow is enabled.

When the owner authorizes paid evaluation, deliberately resume it with the exact pinned corpus, dependencies, scorer and hardware. Baseline generation must use the real protected historical manifest when one exists. Never invent a historical baseline from this skipped release.

```bash
uv run python scripts/run_release_evaluation.py baseline
uv run python scripts/run_release_evaluation.py candidate
uv run python evals/release_gate.py \
  .artifacts/baseline-evaluation.json .artifacts/candidate-evaluation.json
uv run python scripts/release_cloud.py verify
```

Provider/judge errors, empty cases, changed scorer/corpus/hardware, cached results, missing/NaN metrics, safety failures, regressions or inconclusive comparisons block the normal path. Preserve the protected last-approved report; do not reset it to a poorer fresh run. Baseline promotion requires actual evaluation and successful deployment smoke. CI evaluation credentials/roles remain deliberately unconfigured for automatic spending.

## Terraform rollout and hosted checks

1. Confirm profile/account/region and budget, preserve state and a tested Neon backup. Review requirements, exact local worker contracts, extracted ZIP behavior, scans and release authorization.
2. Publish the exact verified bytes with `uv run python scripts/release_cloud.py publish --profile repoguide`. Populate ignored `worker_image_uris` and `release_id` from the resulting real ECR manifest; preserve current 1-vCPU/2-GiB allocations unless new measurements justify a change.
3. Run Terraform fmt/validate, save a full plan and review its JSON. Check exact digests, ZIP hashes, role policies/trust, default desired counts, zero SG ingress, TCP 443/5432 egress, log retention, no NAT/ALB and no external database replacement. Apply the reviewed saved plan.
4. Configure the existing Vercel project's three public `VITE_` values from new Terraform outputs using `scripts/configure_vercel_release.py --apply`. Seed the real dataset catalog with `uv run python scripts/seed_cloud_catalog.py --apply`; it preserves existing reports and creates no scores. Create a production-target deployment with `--skip-domain`; test before promotion. If CLI Git-scope validation fails, use an isolated source snapshot of the same frontend with the existing project IDs; do not disable Git security or create another project.
5. For a protected preview, temporarily allow its exact Vercel HTTPS origin in `validation_frontend_origin` (CORS and Cognito). Use a private documented Vercel automation-bypass cookie for real browser testing. Never expose its secret in a `VITE_` setting. Remove the temporary origin and revoke only the newly created bypass secret after cutover.
6. Run read-only security checks and the native functional test. It creates/deletes temporary Cognito users with invitations suppressed, verifies IAM/JWT/CORS, browsing with zero workers, explicit independent Start, failed-then-healthy jobs, cache, hosted MCP, real index and exact image digests. It stops compute on failure.

```bash
uv run python scripts/aws_security_review.py
uv run python scripts/aws_runtime_smoke.py --phase final --temporary-admin \
  --leave-running-for-idle-test
uv run python scripts/aws_idle_smoke.py
node scripts/browser_cloud_smoke.mjs --readonly
```

The owner deferred this long test for the initial release; it was stopped after 15.3 minutes with both workers zero. Run it later only when deliberately verifying idle behavior. The real idle test intentionally takes about **two hours**: both enter idle, Answer accepts one job at minute 59, Index stops after its original 60-minute window, and Answer stops after its fresh window. It uses actual wall clock, periodically saves evidence and forces both services to zero on exit, with a 150-minute spending safety limit. Do not submit extra jobs during this test. Read-only browsing/status is allowed. Do not represent accelerated-clock unit tests as this production proof.

7. Promote the exact tested Vercel deployment only after required acceptance checks. Verify real production-domain OAuth/Monaco/graphs and no implicit Start. Save private versioned release artifacts/evidence in S3 under `releases/<release_id>/`, **not** an approved-quality-baseline prefix for this skipped release.
8. Confirm original Neon fingerprints unchanged, temporary identities removed, owned test DLQ diagnostics archived before removing only their exact messages, no orphan tasks/IPs, both ECS services at zero and no Terraform drift. Record pending SNS email confirmation and delayed billing honestly.

## Troubleshooting and rollback

Set `VITE_API_BASE_URL`, `VITE_COGNITO_ISSUER` and `VITE_COGNITO_CLIENT_ID` from current outputs; callback/logout is the existing origin plus `/`. OPTIONS must succeed without a JWT, and application routes remain protected. Non-admin Start/Stop returns 403; another user's job deliberately returns 404. Check CSP for Ohio API Gateway/Cognito and locally bundled Monaco/fonts.

After Neon autopause, the first read can take several seconds. An expired pooled SSL connection is retried once **before application SQL**; business queries are never replayed. Repeated readiness errors require checking the scoped SSM reader, TLS URL and Neon availability, without logging the URL/password. Health remains independent of Neon availability.

For worker failures, inspect sanitized job ID/kind/attempt/generation/worker/error type. Jobs have per-message boundaries, bounded retries, leases and DLQs. Do not blindly redrive completed jobs, alter pending counters, purge queues or wake an off worker from backlog. Preserve diagnostic evidence. A failed job should not require restarting the consumer. If both Jev routing and its structured OpenAI fallback fail, routing now degrades safely rather than escaping the job boundary. The answer is marked partial with an explicit routing limitation; always-docs requests select a named declared dependency before a generic declared fallback. No second paid answer generation is performed. Readiness repeatedly failing stops the service and requires explicit administrator action.

Keep previous digest/task definitions, source archive, config and ZIPs. At zero workers, task-configuration rollback can point services to retained measured definitions and restore the current ones, with health/browsing checks. This fresh deployment has **no previous approved whole release**; a component rollback drill cannot establish historical quality or full-release rollback. For future approved releases, restore matching previous image digests, model/prompt config, API/controller ZIPs and the prior Vercel deployment together through a reviewed plan; then repeat hosted checks before moving baseline pointers.

Vercel promotion uses `vercel promote <tested-deployment>` in the existing scope. The saved previous production deployment is in `.artifacts/private/vercel-before-cutover.json`; restore that deployment with the same command if cutover fails, then investigate before retrying.

To pause charges, Drain & stop Answer and Index, then confirm desired/running/pending zero and task public-IP ENIs disappear. Preserve data, secrets, queues, state and release artifacts. **Do not run terraform destroy or delete external resources without a separate cleanup instruction.** Budget alerts are delayed, not hard limits; confirm the SNS email subscription so operational alarms can be delivered.
