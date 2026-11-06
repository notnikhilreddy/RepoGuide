# Product improvement implementation

User decisions, November 5, 2026:

- Reuse the deployed React/Vite, lightweight Lambda, Neon, S3, DynamoDB and independently enabled CPU worker architecture.
- Shared public demo catalog; new indexes are private to their authenticated owner. Assign legacy indexes to the administrator before enabling registration. Keep historical revisions accessible to their owners.
- **Updated scope:** public GitHub repositories only. The owner deferred private GitHub App connections during implementation. No per-user GitHub credentials or new app registration are required.
- Live comparative model evaluation is resumed with a **$2 total ceiling**, including judging/routing, and the AWS rollout must remain **below $10**. Retain the $15/month alert. The prior release's evaluation exception does not authorize a new exception or baseline reset.
- Global compute start/stop remains administrator-only. No automatic worker start. Rolling one-hour idle shutdown and graceful drain remain required.
- Preserve all existing uncommitted work, databases, chats, secrets, backups and Terraform state. Deploy only after validation; remove only verified unused app-owned resources.

## Baseline

The starting working tree passed 135 backend tests, four frontend Node tests, Ruff checks/format, TypeScript, Vite production build, Terraform format and validation. Terraform has existing provider deprecation warnings and the source editor has a large lazy-loaded bundle. Baseline source/configuration is saved privately in `.artifacts/improvement-baseline/`. No live comparative quality result exists yet.

## Work tracking

| Area | Status |
| --- | --- |
| Ownership and access isolation | Implemented; migration/production validation pending |
| S3 conversations and bounded context | Implemented; durability, CAS, isolation and recovery tests passing |
| Public GitHub freshness and incremental indexing | Implemented; isolated PostgreSQL incremental/rollback smoke passed |
| Retrieval, citations and semantic routing | Implemented; baseline complete; rebuilt candidate evaluation running within the shared $2 ledger |
| Landing/auth, architecture, overview, navigation and worker header | Implemented; production-asset browser verification in progress |
| Diagnostics, timeline, feedback and usage | Implemented; backend and browser verification in progress |
| Deployment and production verification | Pending quality gate and exact-image validation |
| Code/cloud cleanup | Code/reference audit in progress; production inventory saved |

Verified locally: 164 backend tests, five frontend Node tests, TypeScript/build, extracted ZIP read-only browsing with owner grants, and Terraform validation. The database backup restored successfully and matches the original two indexes. Both optimized CPU images passed dependency/secret/critical/fixable-high security gates; vendor high-severity findings without fixes remain recorded in the scan reports. No production mutation or application cutover has occurred during this improvement release yet.

See [the product release record](deployment/product-release.md) for scope, storage, safeguards and rollout sequence. This file records verified progress; a listed requirement is not evidence of live acceptance.

The completed baseline is protected and tied to the observed production ECS/Lambda/S3 release identities. Real function-tail/configuration definition retrieval checks pass. The Responses adapter now separates commentary from the final assistant message; the unchanged baseline retains its original behavior.
