# Product improvement implementation

User decisions, November 5, 2026:

- Reuse the deployed React/Vite, lightweight Lambda, Neon, S3, DynamoDB and independently enabled CPU worker architecture.
- Shared public demo catalog; new indexes are private to their authenticated owner. Assign legacy indexes to the administrator before enabling registration. Keep historical revisions accessible to their owners.
- **Updated scope:** public GitHub repositories only. The owner deferred private GitHub App connections during implementation. No per-user GitHub credentials or new app registration are required.
- Live comparative model evaluation is resumed with a **$2 total ceiling**, including judging/routing, and the AWS rollout must remain **below $10**. Retain the $15/month alert. The prior release's evaluation exception does not authorize a new exception or baseline reset.
- Global compute start/stop remains administrator-only. No automatic worker start. Rolling one-hour idle shutdown and graceful drain remain required.
- Preserve all existing uncommitted work, databases, chats, secrets, backups and Terraform state. Deploy only after validation; remove only verified unused app-owned resources.
- November 6: the owner explicitly accepted the measured minor slice tradeoffs and overlapping ranges, authorized publication, and preferred explanatory answers over shortening them for scores. This exact measured acceptance is recorded in `deployment/product-quality-acceptance.json`; all safety and functional checks remain required.

## Baseline

The starting working tree passed 135 backend tests, four frontend Node tests, Ruff checks/format, TypeScript, Vite production build, Terraform format and validation. Terraform has existing provider deprecation warnings and the source editor has a large lazy-loaded bundle. Baseline source/configuration is saved privately in `.artifacts/improvement-baseline/`. Both baseline and the selected explanatory candidate now have complete paired live measurements.

## Work tracking

| Area | Status |
| --- | --- |
| Ownership and access isolation | Migration applied; both original indexes preserved and shared read-only; real two-user API/S3 and private-index isolation passed |
| S3 conversations and bounded context | Implemented; durability, CAS, isolation and recovery tests passing |
| Public GitHub freshness and incremental indexing | Real ordinary-user browser update passed: 156 reused chunks, one embedded chunk; old revision and duplicate-job safety verified. Isolated PostgreSQL add/modify/delete and publication rollback also passed |
| Retrieval, citations and semantic routing | Implemented; completed explanatory candidate accepted with recorded measured tradeoffs |
| Landing/auth, architecture, overview, navigation and worker header | 13 local browser checks and full real preview/production OAuth browser acceptance passed |
| Diagnostics, timeline, feedback and usage | Implemented; backend and local browser verification passed |
| Deployment and production verification | Release `8594722296f0308e` live on existing AWS/Vercel; public registration enabled; native, idle/reset, final production browser and no-drift checks passed |
| Code/cloud cleanup | Reference audit and dependency-aware cleanup completed: 14 task revisions, six old images and three unused Vercel deployments retired; final readback confirms zero workers, task ENIs and queue/DLQ messages |

Verified locally: 188 backend tests, five frontend Node tests, 13 browser checks, TypeScript/build, extracted ZIP read-only browsing with owner grants, and Terraform validation. The database backup restored successfully and matches the original two indexes. Both optimized CPU images passed dependency/secret/critical/fixable-high security gates; vendor high-severity findings without fixes remain recorded in the scan reports. The source scan found no configured credentials in 251 tracked files. Production ownership migration, full native fail/recover/reuse checks, quota enforcement, OAuth browser acceptance, S3 recovery and real incremental indexing passed. Both worker models loaded once. The live application is published and public registration is enabled. AWS recorded both worker idle shutdowns after about 60 minutes 7 seconds; minute-59 reset passed in the earlier observation. The interrupted local observer report is preserved and a separate Answer-hour check completed. Both services are stopped, all queues are empty, alarms are OK and Terraform has no drift.

See [the product release record](deployment/product-release.md) for scope, storage, safeguards and rollout sequence. This file records verified progress; a listed requirement is not evidence of live acceptance.

The completed baseline is protected and tied to the observed production ECS/Lambda/S3 release identities. Real function-tail/configuration definition retrieval checks pass. The Responses adapter now separates commentary from the final assistant message; the unchanged baseline retains its original behavior.

The final accepted quality reference is retained in private versioned S3 with the original measured `6045f7cc62bd` source/image. Production `e7871d59bfd4` is recorded separately with the exact serialization-repair equivalence and live functional evidence. The final release bundle retains the original failed observer receipt and both real idle observations; no continuously observed two-hour lifetime is claimed.
