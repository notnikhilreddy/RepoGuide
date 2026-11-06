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
| Ownership and access isolation | Migration applied; both original indexes preserved and shared read-only; live API isolation pending backend rollout |
| S3 conversations and bounded context | Implemented; durability, CAS, isolation and recovery tests passing |
| Public GitHub freshness and incremental indexing | Implemented; isolated PostgreSQL incremental/rollback smoke passed |
| Retrieval, citations and semantic routing | Implemented; completed explanatory candidate accepted with recorded measured tradeoffs |
| Landing/auth, architecture, overview, navigation and worker header | Implemented; 13 local browser checks passed; live browser acceptance pending rollout |
| Diagnostics, timeline, feedback and usage | Implemented; backend and local browser verification passed |
| Deployment and production verification | Exact-image checks passed; authorized AWS/Vercel rollout in progress |
| Code/cloud cleanup | Code/reference audit completed; read-only cloud inventory and dependency-aware cleanup plan saved |

Verified locally: 175 backend tests, five frontend Node tests, 13 browser checks, TypeScript/build, extracted ZIP read-only browsing with owner grants, and Terraform validation. The database backup restored successfully and matches the original two indexes. Both optimized CPU images passed dependency/secret/critical/fixable-high security gates; vendor high-severity findings without fixes remain recorded in the scan reports. The production ownership migration is applied and original content hashes remain unchanged. Application cutover and live acceptance are in progress; registration remains closed.

See [the product release record](deployment/product-release.md) for scope, storage, safeguards and rollout sequence. This file records verified progress; a listed requirement is not evidence of live acceptance.

The completed baseline is protected and tied to the observed production ECS/Lambda/S3 release identities. Real function-tail/configuration definition retrieval checks pass. The Responses adapter now separates commentary from the final assistant message; the unchanged baseline retains its original behavior.
