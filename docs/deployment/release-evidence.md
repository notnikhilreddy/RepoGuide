# Product improvement release — November 6, 2026

The current release is **`release-8594722296f0308e`**, live at **https://repo-guide-five.vercel.app** on the existing AWS and Vercel resources. The [current product release record](product-release.md) contains exact image/package identities, source provenance, user decisions and practical limits.

Verified for this release: **188 backend tests, five frontend Node tests, 13 local browser tests**, exact extracted ZIP/worker checks, native 1-vCPU/2-GiB failure/recovery/model-reuse checks, full real OAuth production-browser acceptance, owner isolation, S3 delivery/recovery, quota enforcement and real incremental indexing. The real update reused 156 chunks and embedded one changed chunk, preserving the previous revision. Original index content hashes are unchanged after migration and test cleanup.

The explanatory candidate's paired live evaluation improved fact coverage **78.8% → 98.1%** and correctness **91.3% → 99.0%**. The owner accepted the recorded minor slice tradeoffs; the strict comparison remains preserved as failed. Actual measured AI source/image and the production serialization-only repair remain separately identified. No new quality measurements are claimed for the repair.

Dependency-aware cleanup removed **14 unused task revisions, six old ECR digests and three unused Vercel deployments**. Current, original recovery and measured explanatory images remain; databases, conversations, secrets, backups, state and audit evidence were retained. Regional access denial is explicitly unresolved, not absence of resources.

The real idle-window/reset check is still running. Final public-registration, zero-worker and Terraform drift readbacks are pending that observation. The model reservation is currently about $1.50, with one planned bounded idle-reset answer bringing it to about $1.59; AWS rollout is conservatively estimated below $6 and the $15/month alert remains configured. Billing is delayed; no settled actual AWS total is claimed.

## Historical initial release

The following evidence applies to the November 5 release. Its evaluation/idle deferrals and artifact identities do not describe the current release.

> Historical initial-release record. The current improvement release, authorization, scope and verification status are tracked in [product-release.md](product-release.md) and [IMPROVEMENT_STATUS.md](../IMPROVEMENT_STATUS.md). The earlier evaluation/idle deferrals do not authorize a new skipped quality gate.

# Release evidence — November 5, 2026

AWS release **release-e6d2bb0163d23c9f** is deployed in `us-east-2`. Post-fix hosted functional and full production-browser acceptance passed. The existing Vercel domain has been promoted to the exact tested deployment. The owner cancelled the long idle test after 15.3 minutes; it is recorded as skipped, with 60-minute shutdown/reset unverified. The earlier deployment hold was superseded by the owner's OpenAI deployment request.

**Comparative quality evaluation is skipped by owner.** No scores, non-regression result or approved baseline are claimed. The exception binds exact source/config/images; all technical checks remain required. The old Google 503 report and evaluation pause marker remain preserved.

## Exact deployed artifacts

Runtime source SHA256: `21d534cbf513d1fb893393ee7d131dbc1a25b1be220caef5e9ed539b28661c6f`. Source is an archived working tree based on Git commit `4aa70f5cbf345ab83ab7cc14257d79da6a8ee416`; no new commit, push or CI run is claimed.

| Artifact | Size | SHA256 / published ECR digest |
| --- | ---: | --- |
| API ZIP | 5,510,470 bytes | `892604afec13f4ee215e94c44833b83f9b707066715a4a98faa212266ee2ad23` |
| Controller ZIP | 7,504 bytes | `a3713863160671a41923f0dad08732b8fd68eb6f67c96f25f138be43fa9bf7ce` |
| Answer image | 545,305,543 bytes compressed | `sha256:c5ecb2b7ffe6668b2ab0c4fe69aace5266ffca8221ff2587e7e50862d3868ced` |
| Index image | 480,218,210 bytes compressed | `sha256:7790d4d9a17556ece4fa9400d10f5e7b93b01af07e78452845aef4fe92f82620` |

Image requirements are role-specific and hash-locked. Application module closures are staged separately; Answer omits parsers/indexer/Google SDK, Index omits the answer pipeline/OpenAI/MCP graph. Both omit CUDA/NVIDIA, MLflow, build headers, tests and bytecode. Models are pinned and baked offline. Tasks use non-root UID/GID 10001, read-only root, owned `/tmp`, all Linux capabilities dropped, 1 vCPU and 2 GiB. Small image sizes remain constrained by required CPU PyTorch and model weights.

## Completed local checks

| Check | Observed result | Boundary |
| --- | --- | --- |
| Backend suite | **135 passed** | Offline unit/transaction/queue/provenance/provider/release-gate tests |
| Frontend | TypeScript/build and **4 Node tests passed** | Local compiled frontend |
| Offline browser | **4 Playwright tests passed** | HTTP fixtures, distinct from hosted browser proof |
| Exact worker contracts | Both failed-then-healthy, repeated jobs, model-load count 1, same process, pending 0 | Real CPU models/clone/parser/PostgreSQL, Moto transports; Answer generation fixture |
| Extracted API ZIP | Health 2 ms, first ready 0.99 s, warm list p95 21 ms; files/symbols/graph/dependencies passed | Isolated TLS PostgreSQL, SSM mocked, no workers; attempted write rejected |
| OpenAI connectivity | Completed, standard tier, 26 input / 5 output tokens | Availability only |
| Real local answer | Partial answer, six sources, validated citations; 2,967 input / 575 output tokens | Functional smoke, no judge or quality comparison |
| Formatting / Terraform | Ruff, diff checks, fmt/validate passed | Latest scripts/docs checked again at handoff |

The final exact-image Answer contract reached readiness in 43.82 s and finished in 46.94 s; second fixture answer 1.01 s. Index readiness was 20.57 s; forced full RepoGuide reindex plus contract 283.23 s, second deduplicated job 2.03 s. These are emulated local Linux containers and are not native AWS timings.

Trivy 0.76.1 found **zero critical, zero fixable high and zero secret findings** in both exact images. It still reports **45 unfixed high findings in Answer and 53 in Index**. These unresolved advisories are retained in the JSON reports/SBOMs; this is not a claim of zero vulnerabilities. CPU/dependency inventories passed.

## Completed hosted checks before final acceptance

- Terraform created fresh AWS resources using immutable ECR digests, scoped role secrets and two services initially at zero. No previous destroyed resource IDs were reused.
- API browsing, exact files, symbols, graph, dependencies and the honest dataset catalog worked with both services at zero. Public health is independent of Neon/model startup. JWT access tokens are required; ID tokens, anonymous calls and forged admin headers do not grant controls.
- Twenty-two deployed identity-policy allow/deny checks passed. Worker roles cannot read other roles' secrets or consume their queues. ECS trust is account/region scoped; task definitions are non-root, read-only and drop capabilities. Security groups have zero ingress and TCP 443/5432 egress only. S3 blocks all public access; no NAT gateway exists. Policy simulation does not establish effective SCP permissions; real service calls provide separate runtime evidence.
- Neon has separate SELECT-only API/Answer and six-table CRUD Index logins. Workers receive no owner URL. An initially staged owner-bearing Index SSM version was removed before Index ran; the recreated parameter has only the scoped writer. Privilege probes and parameter-history verification passed.
- Native 4-GiB sizing run passed real answer/index jobs. Start-to-ready was about 72 s per worker; process startup about 23 s. A live answer completed in 9.3 s; MarkupSafe indexed in 12.43 s. Native memory peaks were about 479/396 MiB. This sizing baseline preceded the final routing hardening; dependencies and model weights are unchanged, and final exact-digest 2-GiB acceptance is recorded independently.
- The real signed-in preview browser passed Cognito authorization-code/PKCE login, repository browsing, Monaco/symbol outline, dependency/graph views, explicit Answer Start, asynchronous OpenAI answer/citations, citation navigation and graceful Stop. Index stayed off. No JS/CSP errors or automatic browsing Start requests were observed. No browser/API/token mocks were used in this hosted check.
- A stale Neon SSL connection produced a real 503 during final acceptance. The API now reconnects once before executing application SQL; it never replays a business query after yielding a connection. Four regression tests and exact ZIP/worker/image checks passed. The first live read on the fixed release resumed Neon successfully in 3.727 s.

CloudWatch REPORT entries for the final API recorded two initialization samples at **118.13 ms** and **88.6 ms**; this is runtime initialization, separate from Neon resume and end-to-end network latency.

The real shared per-user request budget also passed five accepted requests followed by HTTP 429. No jobs/model calls were made; all five tagged feedback rows and the temporary viewer were removed, with worker idle fields unchanged. Exact final 2-GiB CloudWatch memory maxima so far were 23.828% Answer (~488 MiB) and 23.608% Index (~484 MiB).

After actual Neon compute resume (server start observed at 20:02:52 UTC), the API first read completed in **1.8305 s**, then ten warm reads had **75.6 ms p50 / 207.5 ms p95**. Both worker idle timers and identities remained unchanged.

## Preservation and remaining work

Before rollout, a fresh private Neon backup was restored and checked. Production already held the owner's RepoGuide repository: **508 chunks, 408 symbols, 3,551 edges, 27 dependencies and 89 source snapshots**. No existing repository is reindexed during AWS acceptance. A separate public MarkupSafe repository is the indexing smoke fixture. A full canonical row-value comparison against the restored predeployment backup passed for all six original repository tables, including embeddings and exact source text; Alembic remains `98cc72143f07`. Text hashing uses explicit C collation so differing local/Neon database locales do not create false mismatches.

The existing Vercel project/database/cache are preserved; no duplicate project or Neon production database was created. Temporary smoke Cognito accounts use suppressed invitations and are deleted. The administrator's initial password is stored only in `.artifacts/private/cognito-admin.json`.

Final exact-digest 2-GiB acceptance passed all 12 hosted checks: zero-worker browsing, unauthorized controls, independent admin Start, failed-then-success for each role, validated live citations, cache reuse, job ownership hiding, real Context7 documentation, truthful GitHub partials, real Index persistence and same-process reuse. Final post-fix start-to-ready was 71.95 s Answer / 61.67 s Index; process startup 22.783 / 19.981 s; live answer 15.52 s and full MarkupSafe index 15.54 s. These include network/polling/provider variability.

All nine owned deployment-test DLQ diagnostics were archived to private versioned S3 and only their exact messages removed. This includes the preserved real routing failure, separately identified from deliberate poison jobs. Their durable failed job rows remain; no queue was purged and no unknown message was removed.

The task-definition rollback/restore drill passed with both services at zero; no previous approved whole release exists, so no historical full-release rollback is claimed. The full browser test passed at https://repo-guide-five.vercel.app with real OAuth/Monaco/graph/dependencies/explicit Start/async answer/citations/graceful Stop and zero JS/CSP errors. Temporary Vercel access and the preview callback/CORS origin were removed. All four alarms are OK; SNS email confirmation remains a manual action. The final Terraform plan reports no changes. AWS-normalized empty capability defaults are explicit, preventing repeated task-definition replacements. Runtime images, grants and workloads are unchanged by that normalization. Versioned private S3 retains exact source/config/ZIP/images/SBOM/scan evidence, separately from any approved-quality-baseline prefix. Machine-readable source evidence is under `.artifacts/`; the consolidated record is `reports/deployment-validation.json`.

## Routing availability hardening

A valid hosted documentation question exposed a `JSONDecodeError` escaping the nested Jev-to-OpenAI router fallback. That failed smoke report is retained separately. Both router failures now degrade to a bounded decision; citations still validate and the response is deterministically partial with an explicit routing limitation. Always-docs fallback prefers a named, declared dependency. Five new offline regression cases pass; the full suite is 135 tests. Both rebuilt exact-image contracts and scans passed before publication. No additional paid answer repair or quality judging was introduced.

Final cleanup verifies both services desired/running/pending zero, no running tasks or task ENIs/public IPv4s, empty work queues and DLQs, temporary Cognito users removed, preview callback/CORS access removed and the Vercel automation secret revoked. The final drift plan has detailed exit code 0. The public production browser passed all eleven checks with no JavaScript/CSP errors and only the three explicit Start/ask/Stop POSTs. The protected final report binds native/browser/rollback/cleanup/drift evidence to this release ID.
