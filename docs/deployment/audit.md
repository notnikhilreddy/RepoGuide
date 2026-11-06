> Historical initial-release record. The current improvement release, authorization, scope and verification status are tracked in [product-release.md](product-release.md) and [IMPROVEMENT_STATUS.md](../IMPROVEMENT_STATUS.md). The earlier evaluation/idle deferrals do not authorize a new skipped quality gate.

# Deployment audit — current rollout, November 5, 2026

The owner resumed deployment with OpenAI after the earlier Google availability hold. AWS is now a fresh deployed stack in `us-east-2`; the latest runtime release is `release-e6d2bb0163d23c9f`. Its source is an archived working tree based on commit `4aa70f5`, not a new Git commit. All external production resources are preserved.

| Area | Current verified observation |
| --- | --- |
| AWS / Terraform | Named profile `repoguide`; local backend; fresh resources created without restoring destroyed-resource state. Immutable ECR images, ZIP API/controller and two independent 1-vCPU/2-GiB services. Final native functional checks passed; the owner cancelled the real idle test after 15.3 minutes; hourly shutdown/reset remain unverified in production. |
| Security | 22 identity-policy scope checks and actual IAM-backed calls passed. No SG ingress; only TCP 443/5432 egress; no NAT/ALB. ECS account-scoped trust, non-root UID/GID 10001, read-only root and capabilities dropped. Private encrypted/versioned S3 and scoped SecureStrings. The existing deployment IAM user is administrative; it is not a task role. |
| Neon | Existing production schema/repositories preserved. Before rollout: one RepoGuide repository, 508 chunks, 408 symbols, 3,551 edges, 27 dependencies, 89 source snapshots. Fresh backup restored successfully. API/Answer SELECT-only role and table-scoped Index writer added; no owner credential reaches tasks. Separate MarkupSafe smoke repository indexed. A canonical full-row comparison against the restored predeployment backup passed for all original repository tables, including vectors/source snapshots; Alembic is unchanged. |
| Vercel | Existing `repo-guide` project/root `frontend`/existing domain preserved. Three production VITE values configured from fresh Terraform outputs. Exact tested preview built successfully, real OAuth/Monaco/graph/dependency/async-answer controls passed. The existing production domain now points to the exact tested deployment, and full signed-in production browser acceptance passed. |
| Upstash / MCP | Existing rotated cache verified, real AWS cache hit passed. Context7 hosted documentation passed from AWS. GitHub MCP intentionally unavailable and truthful partial-result behavior passed. |
| OpenAI | `gpt-6-luna`, standard tier, low reasoning, output <=2,000 tokens, input <=32,000 characters; evidence <=12,000 characters. Local availability and live local/AWS answers passed. Comparative quality evaluation is skipped by explicit owner instruction, never passed. |
| GitHub | Old ungated image publisher disabled remotely. Main branch and production/quality environments protected and read back. No source push, automatic deployment, paid CI evaluation or CI-success claim. No CI AWS deployment/OIDC role created. |
| Costs / alerts | Same-day Cost Explorer reports $0, subject to billing lag. Actual retained compressed-image sizes recorded; both workers will finish at zero. SNS email is PendingConfirmation. Existing $15 monthly warning budget has $5 actual/$10 forecast alerts; rollout authorization stays below $10. |

Offline backend tests: **135 passed**. Both exact-image worker contracts, extracted ZIP checks, dependency/secret/vulnerability gates and hosted browser proof passed. Unfixed high OS advisories remain. See [release evidence](release-evidence.md), [sizing](sizing.md), [cost estimate](cost-estimate.md) and [runbooks](runbooks.md) for identities, boundaries and remaining acceptance work.

The following audit was captured before the owner resumed rollout and before the owner added repository data. Its zero-resource/empty-database observations describe that earlier moment only. They do not describe the current stack.

---

# Initial held audit — historical snapshot

## Decision and current state

The owner confirmed the previous Terraform deployment was intentionally destroyed. AWS is a **fresh deployment in us-east-2**. The current instruction is to **leave AWS unchanged** and complete local work while Google AI Studio evaluation is unavailable. No Terraform apply, ECR push, Lambda/ECS deployment, Cognito creation, or Vercel production redeployment has occurred in this session.

The initial approved reference is Git commit `4aa70f5cbf345ab83ab7cc14257d79da6a8ee416` on `main`. Implementation is in the local working tree; there is no new release commit yet. `plan.md` was initially untracked, and an existing user edit to `.gitignore` was preserved. Secrets and local artifacts are ignored.

## Access and resources inspected

| Area | Observed evidence |
| --- | --- |
| AWS | Named profile `repoguide` authenticates as the deployment IAM user; target region us-east-2. ECS clusters, Lambda functions, ECR repositories and Cognito pools were empty at preflight. Account identifiers are omitted here. |
| Terraform | Local backend, Terraform 1.17.1; installed AWS provider 6.71.0. Current state serial 139 has zero resources/outputs. The historical backup has 63 resources and is retained privately. It must **not** be restored as live state after destruction. |
| Costs | Cost Explorer reported zero unblended cost for Nov 1–4 at preflight. Billing data can lag. No new AWS resources were created. |
| Vercel | Existing `repo-guide` project, existing domain https://repo-guide-five.vercel.app, root `frontend`, Vite preset, Node 24. CLI login works. Project was linked locally; no duplicate project was created. Production environment variables were empty when inspected. |
| Neon | Existing production URL in `.env.deploy` is reachable. PostgreSQL 18.6, Alembic revision `98cc72143f07`; database size 8,232,960 bytes at audit. Repository/chunk/symbol/edge/dependency/source-file counts were all zero. No repository data was changed in Neon. |
| Database protection | Custom-format backup captured privately and successfully restored into a disposable PostgreSQL 18/pgvector container. Backups, credentials and raw audit details stay in `.artifacts/private`, not Git. No production migration or role creation was performed. |
| Upstash | Owner confirmed token rotation. A unique TTL=1 second test key was written/read and observed expired. Existing database preserved. |
| GitHub | Connected account has repository admin permissions. Main had no branch protection; there were no environments, Actions secrets or variables. The old ungated image publisher was disabled remotely before any source push. Other protection changes have been prepared locally, not applied. |
| External tools | Context7 hosted MCP returned real documentation using the configured key. GitHub MCP is intentionally disabled at the owner's request; requests needing it must report missing evidence. |

## Baseline and validation

The original offline suite passed **47 tests**. The expanded backend suite, packaged API checks, real-model container harness, frontend browser tests and their exact results are listed in `release-evidence.md`. The React app is Vite/React/TypeScript, not Next.js.

The pinned fixture is the approved RepoGuide commit, indexed only into the disposable local database. Existing historical datasets are retained unchanged. A new versioned corpus checks current paths and includes reference facts, unanswerable questions, injection attempts, citations and routing cases.

The Google model configured by the owner is `gemini-3.5-flash-lite`. A bounded availability probe succeeded. The first live baseline generation subsequently returned **503 UNAVAILABLE / high demand**. Live evaluation requests were paused immediately. The partial report is not an approved baseline; candidate generation/judging, quality comparison and production promotion remain blocked. Offline or fixture results do not substitute for this gate.

## Architecture changes and remaining rollout work

| Keep / change | Result | Migration and rollback |
| --- | --- | --- |
| Keep Neon, Upstash and Vercel | Existing external resources retained; authenticated browsing remains protected | No production data migration performed |
| Replace heavy Lambda image | Standard-library handler plus psycopg binary ZIP; lazy SSM/DB access; independent health endpoint | Fresh AWS creation; no old Lambda to roll back to |
| Replace automatic worker activation | Two independently controlled services, transactional jobs/outbox, generation/lease fencing, 60-minute idle shutdown | Desired count starts at zero; no queue-triggered scale-up |
| Add split worker builds | CPU-only pinned requirements, pinned model revisions, offline non-root execution | Preserve exact evaluated image digests and one previous approved release |
| Replace release bypasses | Failing publisher retired; strict comparator, guarded publisher and Terraform preconditions | Missing/failed evidence blocks changes; baseline is promoted only after smoke |
| Correct frontend hosting assumptions | Async job polling, admin controls, local Monaco workers/fonts, Ohio CSP, Git auto-deploy disabled in source | Existing Vercel project only; no production promotion during this session |

Full production Terraform planning/apply, ECR publishing, live IAM/Cognito/CORS tests, native Fargate sizing, real SQS failure tests, the actual 60-minute idle test, Vercel cutover and rollback smoke remain **unperformed**. The ECR-only bootstrap plan is a read-only preview and was not applied. Full runtime plans require approved evaluation and immutable published release evidence.
