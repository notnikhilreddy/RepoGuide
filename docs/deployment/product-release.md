# Product improvement release

This work implements `RepoGuide_Improvement_Plan.md` against the existing React/Vite application, small ZIP API Lambda, Neon/pgvector, S3, DynamoDB/SQS and separate CPU ECS workers. This is the current implementation record; the earlier initial-release documents describe historical deployment evidence.

## Scope and storage

Public GitHub repositories are supported. The owner deferred private repository connections; no GitHub App registration or new credential is needed. Existing verified-public demo indexes are shared read-only. New indexes belong to the authenticated user, including when two users index the same public URL and commit. Older revisions remain usable. SQL migration `b42d92e7a610` adds ownership, parent revision and index diagnostics without replacing existing data. Legacy indexes must be assigned to the existing administrator and granted before public registration is enabled.

Conversation messages, answers, citation metadata, active turns and interruption state are authoritative in private S3. DynamoDB contains scoped listing metadata and job delivery state. Conditional S3 writes protect competing tabs. Large answer bodies spill into private conversation assets. A controller delivery outbox retains terminal results until saved, without enabling ECS or extending idle time. Deleting a chat tombstones its metadata before cancelling work; current objects are deleted and noncurrent versions expire after seven days. Feedback can reference a saved message after the temporary job expires. Usage and feedback metadata expire after 90 days.

The local development API retains browser-only conversation storage, clearly labelled in the UI. Hosted sessions always use owner-scoped S3. Active conversation IDs in local storage contain no message bodies and are validated by the hosted API on every load.

## Retrieval and indexing

Follow-ups use at most six bounded history turns. Prior assistant prose is context, never repository evidence. Exact focus, symbol neighbors and file diversity supplement hybrid retrieval before one rerank. Evidence carries the repository ID, indexed SHA, original path and line range; the UI opens that indexed source or exact GitHub commit. Documentation has independent D labels and only observed HTTPS source URLs. Citation label validation does not prove semantic entailment; Inspect states its scope honestly.

Additional source/manifests and late JavaScript/TypeScript module windows are searchable. Structural graph parsing remains Python, JavaScript and TypeScript; other collected text languages do not acquire fabricated relationships. Overview and architecture are derived from indexed evidence, using stable module drilldown, bounded nodes/edges and scoped search.

Remote checks use public GitHub REST, shared cooldowns and a conservative hourly request limit. Each repository's monitored branch is checked while the app is active; failures differ from “up to date.” An update is explicit. The new revision rebuilds graph/source metadata and reuses unchanged embeddings only in the same pinned embedding space. Publication is atomic; failures retain the old index. Health exposes excluded/failed files, warnings, revision and reuse diagnostics. Legacy diagnostics are explicitly unavailable until a new index is built.

## Operations and safeguards

Cognito registration, verification and recovery are integrated. Enable `enable_public_registration` only after migration, owner grants and new API isolation smoke checks. The first backend Terraform apply must keep it false. Administrator-only worker controls live in the header. New account sign-up, browsing, queue traffic, failures and delivery retries never start a worker. Startup requires real model/database readiness; graceful stop finishes current work and rejects new jobs. One continuous hour without queued/active work stops the worker; no two-hour lifetime limit is added.

Per-owner quotas, two outstanding jobs per worker, global daily budgets, public repository size limits, bounded source/chunk counts and database capacity checks constrain the demo. Queued jobs expire after 24 hours and release counters. Repository contents remain in Neon, with only permission/freshness attributes in DynamoDB. No new always-on service, NAT gateway or tracking server is added.

Hosted model/router configuration is OpenAI `gpt-6-luna`, default tier, bounded input/output, low answer reasoning and semantic routing. MLflow remains disabled in hosted workers. Request-local traces capture major stages, safe counts/timings, a trace ID and measured token/cost estimates. Inspect, usage, feedback and detailed worker state are secondary surfaces.

## Validation and spending

Live before/after evaluation uses the exact starting deployed image/source and frozen candidate image, the same 13 pinned questions and routing probes, two repetitions and a shared fail-closed $2 reservation ledger. Failed attempts and unused reservations remain recorded. Scoring uses a strict typed judgment schema. A baseline measured from the previously owner-skipped release must be bound to its current ECS/Lambda identities and immutable S3 artifacts; it cannot replace a protected approved quality report. Existing non-regression and safety gates remain in force.

The AWS rollout ceiling is below $10 and the existing $15/month alert is retained. The database backup has been restored locally and its original content hashes match. Production migration, deployment and live acceptance are recorded only after they actually succeed. Private backups, secrets and Terraform state are never committed.
