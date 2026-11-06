# RepoGuide — Product Quality & Feature Improvement Plan

> **For Codex (GPT-6.1 Sol, High):** Inspect the actual repository first, determine root causes, and implement this plan with your own engineering judgment. This is a product/acceptance brief, not a prescribed solution. Prefer improvements to existing components over a rewrite.

## Goal

Turn RepoGuide into a reliable, polished, production-quality AI codebase explorer with strong retrieval, persistent conversations, meaningful visual exploration, and transparent engineering diagnostics.

**Most important UX principle:** Sophisticated internals, simple interface. Keep the main UI clean, fast, professional, and approachable. Use progressive disclosure: show essential information by default; expose advanced diagnostics and controls only when requested. Take visual inspiration from refined developer products such as Linear, GitHub, and Vercel without cloning them. Add subtle, purposeful animations—not clutter.

## Guardrails

- Work with the existing architecture and stack (Next.js/React, FastAPI, LangGraph/MCP, PostgreSQL/pgvector, Redis, Cognito, S3, SQS, ECS Fargate, Vercel/AWS, MLflow/OpenTelemetry, etc.) as actually implemented. Do not assume all named services are active; inspect first.
- Preserve low idle cost for a lightly used public demo. Avoid new always-on services, unnecessarily frequent polling, and expensive LLM/tool calls.
- Keep authentication, ownership isolation, input validation, rate limiting, job idempotency, and secrets handling sound.
- Do not hardcode specific keywords, repositories, examples, graph structure, or benchmark answers to make features appear to work.
- Do not weaken evidence requirements just to eliminate abstentions; improve retrieval and reasoning instead.
- Maintain compatibility with existing indexed repositories/data where reasonable; document required migrations/reindexing.
- **Deployment is authorized:** implement, validate, and deploy the finished application to the existing AWS and Vercel environments, including required Terraform changes and migrations. Keep costs minimal and reuse existing infrastructure. Never delete shared/unrelated resources or compromise user data.

## Workstreams

### A. Answer quality, citations, and intelligent retrieval

1. **Fix citations end to end.** Trace ingestion → chunk metadata → retrieval → response schema → frontend. Make citations visible and clickable, opening the appropriate GitHub file/commit/lines, indexed source preview, or official external documentation. Keep citation metadata with saved messages. Handle private/missing/stale links safely; never fabricate links.
2. **Generalize MCP documentation routing.** Audit for keyword-based or brittle triggers. Decide when external documentation is needed based on question intent, available repository evidence, dependencies, and sufficiency; avoid unnecessary calls. Handle MCP failures and version-aware sources gracefully.
3. **Improve retrieval substantially.** Diagnose incomplete/irrelevant responses and false “insufficient evidence” decisions. Review ingestion coverage, chunking, embeddings, hybrid search, filters, reranking, contextual/multi-hop retrieval, relevant neighbor expansion, and sufficiency logic. Make cross-file explanations accurate and well supported.
4. **Make chat conversational.** Follow-up questions must use relevant history to resolve references and retrieve the right evidence, without stuffing unbounded conversation history into each prompt. Maintain answer quality and citations across turns.
5. **Measure improvement.** Reuse or extend the existing eval suite with realistic single-file, cross-file, architecture, documentation, unanswerable, and multi-turn questions. Compare retrieval relevance, citation correctness, answer faithfulness, false abstentions, latency, and cost before/after.

### B. Durable, user-owned conversations

6. **Persistent conversation history.** Store chats and their citation/evidence metadata durably in **S3**, with efficient metadata/listing support using existing infrastructure as appropriate. Each authenticated user can start a new conversation, browse/search previous chats, rename and delete them, and resume from another device. Refreshing or reopening the page must not clear history. Save active conversation state safely, including interrupted/failed generations.
7. **Conversation UI.** Build a polished, compact history sidebar/drawer, clean message rendering, source/citation interactions, useful loading/streaming/stop states, and friendly empty states. Keep repository context clear and prevent cross-user or cross-repository leakage.

### C. Code exploration and repository lifecycle

8. **Replace the cluttered graph experience.** Default to a small number of meaningful high-level architecture/module nodes. Click to expand into progressively deeper levels, using stable layouts, breadcrumbs, smooth transitions, and searchable navigation—not a giant draggable force canvas. Show only meaningful incoming/outgoing relationships by default; collapse trivial or repeated edges. Node details should offer code preview and **Ask about this**.
9. **Repository overview.** After indexing, show an accurate, concise overview: architecture, major modules, dependencies/tech stack, entry points, indexing status, and helpful suggested questions. Ground summaries in actual indexed evidence.
10. **Source-to-chat navigation.** From any file, symbol, graph node, or evidence item, let the user ask a context-specific question without copying code manually.
11. **Indexing health.** Expose useful diagnostics: indexed/excluded/failed files, chunks, revision/SHA, warnings, freshness, and job stages. Keep this compact by default with expandable details.
12. **GitHub commit updates.** For **every previously indexed repository**, track the indexed commit SHA and monitored branch (default branch unless configured). Detect when the remote branch has advanced and surface a clear **“Update available”** in-app notification/badge with the new commit information. Use a cost- and rate-limit-conscious check (for example, periodic checks when the app is active and/or a lightweight scheduled check); respect GitHub API limits and private-repo permissions. Never reindex automatically just because a commit exists. Distinguish an update-detection failure from “up to date.”
13. **One-click incremental reindexing.** Add **Update index** on repositories with new commits. Compare indexed vs target revision; process added/modified files, remove deleted/stale chunks and graph edges, update dependent metadata, and leave unaffected files intact whenever feasible. Preserve old usable index until the new revision is ready; make retries, failures, duplicate clicks, and concurrent jobs safe. Fall back to a full reindex if necessary and explain why. Update freshness badges and summaries after completion.

### D. Authentication, worker management, and public-demo safety

14. **Cognito sign-up.** Enable and integrate new-account registration, email verification, password recovery, sign-in/out, and proper session handling. Preserve existing accounts and correctly authorize all user-owned resources.
15. **Real landing/auth experience.** Replace the bare login form with a professional, responsive, attractive product landing/sign-in page explaining RepoGuide, with clear Sign in / Create account actions and elegant transitions.
16. **Worker controls in the top bar.** Remove the dedicated worker-control section. Show compact Start/Stop and accurate states (stopped/starting/running/busy/idle countdown/stopping/error) in the global header, with an expandable mini-panel for queue depth, progress, and failures. Keep detailed progress within indexing views. Preserve the intended lifecycle: manually started workers keep running while receiving/processing jobs, auto-stop after **one hour idle** (no two-hour hard cap), and stop safely when requested. A failed job must not block future jobs. Guard against duplicate starts and unsafe termination of active work.
17. **Public demo safeguards.** Apply practical per-user quotas, indexing/repository-size limits, concurrency controls, and anti-abuse protection. Ensure users cannot control other users’ jobs/data; carefully separate global/admin worker actions from ordinary user permissions. Keep operational costs bounded without harming normal demos.

### E. Observability and developer diagnostics

18. **Clean MLflow/OpenTelemetry traces.** Produce concise, hierarchical, nonduplicated traces for major stages—routing, retrieval, reranking, MCP (if used), generation, verification, and indexing. Capture useful timings, counts, decisions, token/cost estimates, errors, and trace IDs. Avoid noisy utility spans, repetitive giant payloads, personal data, and secrets. Make it easy to understand one request at a glance.
19. **Retrieval debugger.** Add an opt-in **Developer / Inspect** panel for retrieved candidates, scores, selected evidence, reranking/sufficiency decisions, and reasons for rejection/abstention. Keep raw diagnostics out of the default chat view.
20. **AI execution timeline.** Show meaningful live stages of a request (retrieval → reranking → MCP when needed → generation → citation checks) with accurate progress/status, not fake percentages. Advanced timings belong in an expandable view.
21. **Answer feedback.** Add lightweight positive/negative feedback and optional issue categories (irrelevant, incorrect, missing evidence, bad citation). Store trace/message linkage so feedback can inform offline evaluation.
22. **Usage dashboard.** Expose a compact view of token/API-cost estimates, latency, requests, retrieval/quality metrics, and indexing usage, with appropriate per-user/admin boundaries. Keep the default app uncluttered.

### F. Cohesive, professional UI refinement

23. **Unified visual system.** Refine typography, spacing, color, navigation, cards, forms, empty/error/loading states, dialogs, icons, responsive layouts, and accessible interactions. Smooth, restrained animations should clarify interactions, not compete for attention. Support reduced motion.
24. **Command palette.** Add a `Cmd/Ctrl + K` quick navigator for repositories, conversations, files/modules, and common actions. Keep discoverability and keyboard accessibility strong.
25. **Information architecture.** Ensure the default experience remains simple: select repository → explore overview/graph or ask a question → inspect sources. Put diagnostics, traces, usage, and detailed worker controls behind clear secondary surfaces; avoid accumulating separate oversized dashboards and panels.

## Suggested implementation sequence

1. **Audit and baseline:** Map the current frontend/backend/cloud flows, confirm root causes, run existing tests and retrieval evals, and identify dependencies/migrations.
2. **Correctness first:** Fix retrieval, citations, MCP decisions, conversation context, and evaluation quality.
3. **Persistence and lifecycle:** Implement user-owned saved chat, Cognito sign-up, commit freshness checks, and incremental indexing.
4. **Product UX:** Rebuild graph exploration, landing/auth, chat/navigation, worker header controls, repository overview, command palette, and source interactions.
5. **Developer visibility:** Refine MLflow traces and add the optional inspector, timeline, feedback, indexing health, and usage surfaces.
6. **Deploy and verify:** Build/test optimized images, validate Terraform, deploy the backend and workers to AWS and the frontend to Vercel. Run production health checks and end-to-end smoke tests; fix deployment issues.
7. **Final polish and cleanup:** Harmonize UX, security, docs, and tests. Remove obsolete code and safely retire unused app-owned resources.

Sequence can change based on real dependencies discovered during inspection; prefer reviewable increments over one giant rewrite.

## Verification and delivery

- Test representative happy paths, failures, refresh/login cycles, multi-user isolation, private/public GitHub repositories, stale revisions, interrupted jobs, graph scale, and accessibility/responsive behavior.
- Verify citations actually open the correct content; conversational follow-ups are contextual; reindexing only updates changed content; new GitHub commits produce a clear update notification; old index remains usable through failures.
- Evaluate RAG quality before/after. Check API and infrastructure cost implications, especially polling, token usage, storage, and ECS lifecycles.
- Run relevant tests, lint/type checks/builds, Terraform validation, and production deployment. Verify live functionality and document anything blocked by access or environment constraints.
- Provide a concise completion report: changes, files/modules, configuration/migrations, tests/eval results, live AWS/Vercel deployment status and URLs, resources removed/retained, cost estimates, and remaining limitations.

### Mandatory final cleanup — code and cloud

After all features are integrated and validated, **audit the entire codebase for unnecessary/unused files, dead code, obsolete components, duplicated implementations, outdated scripts/configuration, abandoned experiments, and no-longer-referenced dependencies**. Remove or consolidate these **only after verifying references and preserving functional tests, migrations, infrastructure state, and important docs**. Remove temporary debug code and stale artifacts; update documentation to match the actual implementation. Do not remove code just because it is not exercised by current tests.

**Cloud cost cleanup (required):** Audit AWS, Vercel, ECR, and deployment artifacts against the intended infrastructure and live dependencies. Identify and safely delete verified-unused **RepoGuide-owned** ECR images/repositories, old ECS tasks/services, stale Lambda/API Gateway resources, obsolete S3 build artifacts, redundant queues/tables, duplicate Vercel projects/deployments, and other abandoned infrastructure. Configure sensible ECR/S3 lifecycle policies and CloudWatch log retention. Optimize production images (CPU-only where appropriate) and right-size ECS task CPU/memory based on tests. Avoid unnecessary always-on infrastructure, NAT gateways, and frequent polling.

**Deletion safety:** Before removing any cloud resource, verify ownership, Terraform state, dependencies, active usage, and backup/recovery needs. Never destroy shared/unrelated services or valuable data including chats, indexes, secrets, and infrastructure state. If uncertain, keep the resource and flag it for review. Maintain Terraform state consistency. Record deleted resources and estimated cost savings. Perform final live smoke tests after cleanup and verify worker idle shutdown remains safe for active jobs.

**Definition of done:** RepoGuide is accurate, conversational, persistent, easy to explore, secure for a public demo, cost-conscious, observably engineered, and visually professional—even though it has sophisticated features behind the scenes.
