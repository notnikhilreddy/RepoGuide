# Product improvement release

This work implements `RepoGuide_Improvement_Plan.md` against the existing React/Vite application, small ZIP API Lambda, Neon/pgvector, S3, DynamoDB/SQS and separate CPU ECS workers. This is the current implementation record; the earlier initial-release documents describe historical deployment evidence.

## Live deployment — November 6, 2026

The published application is **https://repo-guide-five.vercel.app**. AWS release `release-8594722296f0308e` is deployed in Ohio (`us-east-2`), with Python source `e7871d59bfd4f0a9870bae1f9ba364d25d7b6e1d6a044859d625655ae1f77b5a`. The existing Vercel project serves the tested deployment `dpl_BzfeD8egzoxnjJX5LLxzAjUJMRNQ`. API URL: `https://701t28kwsb.execute-api.us-east-2.amazonaws.com`.

| Artifact | Exact identity |
| --- | --- |
| Answer image | `sha256:f7d908c142f186130d18f116a81b02f2c0f5a32120d1cce335451ee71f0bae81` |
| Index image | `sha256:f12c97b03af05dedd88d47d69780a3e85f1a995a67b494b0b69b26508b41250a` |
| API ZIP, 5,529,909 bytes | `f4bb77200a026c37a1fde8b7f3c7aca39700730260bbd35616c39a438192d0e1` |
| Controller ZIP, 15,477 bytes | `958a41e68a07c4a21fabe6b7a7be816beaecf3ad850d5d8ce8f42bda901ff039` |

Local validation passed 188 backend tests, five frontend Node tests, 13 Playwright tests, TypeScript/build, Ruff and Terraform validation. Real production OAuth/browser checks passed saved S3 answers, refresh, follow-ups, feedback, exact-commit citations, source navigation, bounded architecture and browsing without starting compute. Native Fargate checked failed-then-healthy jobs, independent controls, model/process reuse, uncached generation, Context7, cache hits and a full index followed by a deduplicated repeat. Quota enforcement and two-user API/S3/index isolation passed. The original two indexes still match their pre-migration content hashes.

The real ordinary-user incremental update detected an actual upstream MarkupSafe commit, displayed **Update available**, and reused 156 chunks while embedding one changed chunk. The prior revision stayed readable and duplicate submissions reused the existing job. A separate disposable PostgreSQL test covers added, modified and deleted files plus interrupted publication rollback; the live upstream commit changed one file and did not delete files.

**Public registration is enabled.** Final two-user API and read-only production-browser acceptance passed with both workers stopped, and Terraform reported no changes (detailed exit code 0). Both work queues and DLQs are empty; there are no running tasks, task ENIs or worker public IPv4s. Temporary test accounts, preview callback/CORS access and the automation bypass were removed. All four operational alarms are OK and the SNS email subscription is confirmed.

AWS recorded Index shutdown after **3,607.114 seconds** and Answer shutdown after **3,606.959 seconds** of real idle time. The minute-59 request was accepted after 3,552 seconds and kept Answer running beyond its old deadline. Laptop sleep interrupted that first local observer, whose safety cleanup stopped Answer early; its failed report is preserved. A separate complete real Answer-hour observation supplied the Answer shutdown proof. The final receipt keeps these observations distinct and does not claim one continuously observed two-hour worker lifetime. No clock acceleration or extra model generation was used for the repeat.

## Changed modules

| Area | Main implementation |
| --- | --- |
| Hosted ownership, conversations, usage and durable result delivery | `src/repoguide/cloud_product.py`, `cloud_features.py`, `cloud_api.py`, `cloud_state.py`, `cloud_scaler.py` |
| Schema and incremental revision publication | `migrations/versions/`, `src/repoguide/models.py`, `indexer.py`, `parser.py`, `intelligence.py` |
| Retrieval, routing, citations and bounded context | `src/repoguide/retriever.py`, `retrieval_exact.py`, `retrieval_context.py`, `router.py`, `pipeline.py`, `answers.py`, `llm.py`, `telemetry.py` |
| Landing/auth, history, architecture, source and command navigation | `frontend/src/` |
| CPU packages, quotas, retention and release evidence | `deployment/`, `docker/`, `infra/terraform/`, `scripts/`, `evals/` |

## Scope and storage

Public GitHub repositories are supported. The owner deferred private repository connections; no GitHub App registration or new credential is needed. Existing verified-public demo indexes are shared read-only. New indexes belong to the authenticated user, including when two users index the same public URL and commit. Older revisions remain usable. SQL migration `b42d92e7a610` adds ownership, parent revision and index diagnostics without replacing existing data. Both legacy indexes were assigned to the existing administrator and granted for shared read-only access before public registration was enabled.

Conversation messages, answers, citation metadata, active turns and interruption state are authoritative in private S3. DynamoDB contains scoped listing metadata and job delivery state. Conditional S3 writes protect competing tabs. Large answer bodies spill into private conversation assets. A controller delivery outbox retains terminal results until saved, without enabling ECS or extending idle time. Deleting a chat tombstones its metadata before cancelling work; current objects are deleted and noncurrent versions expire after seven days. Feedback can reference a saved message after the temporary job expires. Usage and feedback metadata expire after 90 days.

The local development API retains browser-only conversation storage, clearly labelled in the UI. Hosted sessions always use owner-scoped S3. Active conversation IDs in local storage contain no message bodies and are validated by the hosted API on every load.

## Retrieval and indexing

Follow-ups use at most six bounded history turns. Prior assistant prose is context, never repository evidence. Exact focus, symbol neighbors and file diversity supplement hybrid retrieval before one rerank. Evidence carries the repository ID, indexed SHA, original path and line range; the UI opens that indexed source or exact GitHub commit. Documentation has independent D labels and only observed HTTPS source URLs. Citation label validation does not prove semantic entailment; Inspect states its scope honestly.

Additional source/manifests and late JavaScript/TypeScript module windows are searchable. Structural graph parsing remains Python, JavaScript and TypeScript; other collected text languages do not acquire fabricated relationships. Overview and architecture are derived from indexed evidence, using stable module drilldown, bounded nodes/edges and scoped search.

Remote checks use public GitHub REST, shared cooldowns and a conservative hourly request limit. Each repository's monitored branch is checked while the app is active; failures differ from “up to date.” An update is explicit. The new revision rebuilds graph/source metadata and reuses unchanged embeddings only in the same pinned embedding space. Publication is atomic; failures retain the old index. Health exposes excluded/failed files, warnings, revision and reuse diagnostics. Legacy diagnostics are explicitly unavailable until a new index is built.

## Operations and safeguards

Cognito registration, verification and recovery are integrated. Enable `enable_public_registration` only after migration, owner grants and new API isolation smoke checks. The initial migration/rollout kept it false until live isolation checks and the controlled idle observation finished. Administrator-only worker controls live in the header. New account sign-up, browsing, queue traffic, failures and delivery retries never start a worker. Startup requires real model/database readiness; graceful stop finishes current work and rejects new jobs. One continuous hour without queued/active work stops the worker; no two-hour lifetime limit is added.

Per-owner quotas, two outstanding jobs per worker, global daily budgets, public repository size limits, bounded source/chunk counts and database capacity checks constrain the demo. Queued jobs expire after 24 hours and release counters. Repository contents remain in Neon, with only permission/freshness attributes in DynamoDB. No new always-on service, NAT gateway or tracking server is added.

Hosted model/router configuration is OpenAI `gpt-6-luna`, default tier, bounded input/output, low answer reasoning and semantic routing. MLflow remains disabled in hosted workers. Request-local traces capture major stages, safe counts/timings, a trace ID and measured token/cost estimates. Inspect, usage, feedback and detailed worker state are secondary surfaces.

## Validation and spending

Live before/after evaluation uses the exact starting deployed image/source and frozen candidate image, the same 13 pinned questions and routing probes, two repetitions and a shared fail-closed $2 reservation ledger. Failed attempts and unused reservations remain recorded. Scoring uses a strict typed judgment schema. A baseline measured from the previously owner-skipped release must be bound to its current ECS/Lambda identities and immutable S3 artifacts; it cannot replace a protected approved quality report.

On November 6 the owner explicitly authorized publication with less rigid regression acceptance and preferred explanatory answers over shortening them for scores. The selected fully measured source is `6045f7cc62bd`: fact coverage increased from 78.8% to 98.1%, correctness from 91.3% to 99.0%, citation precision from 93.3% to 97.1%, and false-answer rate fell from 3.8% to zero. Two questions had minor slice regressions: provenance relevance and grounding citation/supported-claim precision averaged 87.5% versus 100%. Overlapping observed ranges are retained rather than treated as automatic rejection. `deployment/product-quality-acceptance.json` binds this explicit acceptance to the exact measured report/source; additional/global regressions, missing evidence and failed safety checks remain blocked. The original strict comparison is retained separately and is never described as passing. A shorter-answer experiment was stopped after it omitted relevant caller input transformations; its partial measurements are preserved, not used for publication. No further prompt tuning or live quality-model run was performed for the serialization-only repair described below.

The final conservative model reservation is **$1.592115 of $2**, including failed/unused attempts and live functional requests. Recorded comparative evaluation usage is about $0.1051; functional reservations are upper bounds rather than invented token charges. The AWS rollout is estimated below $6, under its $10 ceiling, and the existing $15/month alert is retained. Same-day AWS billing is delayed; see [the cost review](cost-estimate.md). The database backup has been restored locally and its original content hashes match. Production migration, deployment and live acceptance are recorded only after they actually succeed. Private backups, secrets and Terraform state are never committed.

Real browser acceptance found that DynamoDB decodes progress timestamps as `Decimal`, which the S3 conversation serializer did not accept. The answer job had completed and its result was retained; the repaired serializer recovered that exact answer and citations without paid regeneration. The regression test now exercises real DynamoDB-decoded progress events. Source `e7871d59bfd4` changes only `cloud_product.py` relative to the measured explanatory source. `scripts/operational_equivalence.py` verifies the exact reviewed file hashes, every unchanged answer/retrieval module, frozen model/router configuration, dependencies and image identities. Evaluation reports retain their original measured source/image; no new scores are claimed for the serialization repair. Both the measured and current worker images are retained. The new packages receive separate API, worker and live functional checks. After complete real deployment acceptance, the protected S3 quality pointer was promoted to the actual measured `6045f7cc62bd` reference. Its original Git/source/image/configuration identities remain intact; separate `production_acceptance` metadata identifies release `8594722296f0308e` and the verified serialization-only repair. This does not claim a fresh measurement of the repaired image.

## Rollback boundaries

After public accounts/private indexes exist, **do not restore the old shared-catalog API**: it predates owner isolation. Disabling new registration does not revoke existing viewer accounts. Retain the starting image/source/database backup as recovery evidence, and use a forward fix or a compatible release that enforces current ACLs. A task-definition rollback drill at desired/running/pending zero does not establish that a historical worker is safe to run against the new ownership schema. Database downgrade refuses duplicate URL/commit rows across owners; do not delete user indexes to force it through. New S3 chats and historical repository revisions must survive recovery.

Production failure/recovery smoke must use `scripts/aws_runtime_smoke.py --phase final --temporary-admin` so its forced test index belongs to a new isolated identity. That helper removes only the test identity's MarkupSafe rows/grants; the original two indexes are fenced by the verified backup IDs. A final read-only content comparison uses the restored product backup proof and excludes only the new ownership/diagnostic columns.

Cloud cleanup is a reviewed plan followed by `--apply` in `scripts/product_cloud_cleanup.py` and `scripts/product_vercel_cleanup.py`. The former checks cross-cluster ECS services/tasks, dormant EventBridge rules/schedules and image-based Lambdas, and resolves mutable image tags before retiring old worker images/task revisions; the latter preserves current/recovery and every active alias deployment in the existing project. Neither helper removes databases, conversations, queues, secrets, backups, state or release audit archives. Logical compressed image sizes do not establish actual billed storage savings because layers are shared. A regional inventory covers the deployed region and the prior target region; an access denial is recorded as unresolved, never as absence or permission to delete.

Cleanup retired **14 unused task revisions, six old ECR image digests and three unused Vercel deployments**. Current images, the original recovery pair and the exact measured explanatory pair remain: three images per role. The retired image byte sum is 3,076,570,642 bytes before shared-layer deduplication; actual storage savings require billing data. This does not claim Vercel runtime savings. All currently referenced deployments/aliases, original indexes, conversations, secrets, backups and Terraform state were retained. The prior region `us-east-1` denied inventory access; its resources remain unresolved and untouched.

## Practical limits

Private GitHub connections are deferred by the owner. Public repositories added by a user remain private within RepoGuide. Administrator-started workers are required for indexing or answers; browsing and saved history work while workers are stopped. The per-user and global quotas intentionally bound a lightly used demo.

Email verification/recovery forms and Cognito configuration are covered, but delivery to a real mailbox has not been exercised. Native memory figures are one-minute CloudWatch samples, not instantaneous RSS peaks. The paired evaluation latency was measured under Linux/amd64 emulation on Apple Silicon; its 9.8-to-42.4-second warm p95 change is not a native production benchmark. Native representative jobs took 15.77 seconds for an answer and 15.68 seconds for a full small-repository index, which are individual observations rather than p95 estimates.

Both exact images passed zero-secret, zero-critical and zero-fixable-high scan gates. Vendor advisories without available fixes remain: 46 high findings in Answer and 54 in Index. Monaco is separately loaded and remains a large bundle; Terraform emits existing DynamoDB key deprecation warnings. These are retained findings, not claims of a warning-free build or unlimited repository capacity.
