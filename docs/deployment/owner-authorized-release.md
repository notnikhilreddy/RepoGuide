> Historical initial-release record. The current improvement release, authorization, scope and verification status are tracked in [product-release.md](product-release.md) and [IMPROVEMENT_STATUS.md](../IMPROVEMENT_STATUS.md). The earlier evaluation/idle deferrals do not authorize a new skipped quality gate.

# Initial OpenAI deployment authorization — November 5, 2026

The owner resumed AWS deployment and explicitly requested skipping paid CI evaluation to avoid token costs. This supersedes the earlier deployment hold for this release. Evaluation is recorded as **skipped by owner**, never passed; no quality score, approved baseline or non-regression claim is invented.

The exception is limited to the exact source, non-secret configuration, Terraform configuration and local worker identities recorded in `deployment/release-authorization.json`. A changed release fails verification. All ordinary functional, provenance, packaged API, worker isolation, CPU dependency and security checks remain required. Baseline promotion rejects a skipped evaluation. Future releases retain the normal evaluated path unless separately authorized.

The selected model is `gpt-6-luna`, using Responses with `service_tier=default`, low reasoning effort, at most 2,000 output tokens and a 32,000-character full-request ceiling. Repository evidence is packed within 12,000 characters. Short context is a pricing threshold, not a separate model or API context-length flag. No silent evidence truncation or paid response repair is used.

Official sources checked November 5: [GPT-6 Luna pricing and supported reasoning](https://developers.openai.com/api/docs/models/gpt-6-luna), [standard service-tier semantics](https://developers.openai.com/api/reference/cli/resources/responses/methods/create). Standard short-context rates are $0.10/M input, $0.50/M output and $0.01/M cached input. Cache writes and other optional services have separate pricing; no explicit paid cache-write policy is requested.

Before AWS mutation, 125 offline tests passed, both exact-image worker contracts passed failed-then-success and model reuse, and the extracted API ZIP passed against isolated TLS PostgreSQL. A real OpenAI answer used 2,967 input and 575 output tokens on the standard tier and returned a truthful partial result with validated source citations. This is a functional smoke test, not a comparative quality evaluation.

A fresh private Neon backup was restored successfully before deployment. Production already contained one repository, 508 chunks, 408 symbols, 3,551 edges, 27 dependencies and 89 source snapshots at this resumed audit; preserve these records. The earlier empty-database audit is historical. Existing Vercel, Neon and Upstash are reused. GitHub MCP remains unavailable at the owner's request. Paid CI evaluation is not triggered and the prior partial evaluation reports are retained unchanged.

The owner later deferred live 60-minute idle/reset verification, cancelling the observation after 15.3 minutes and asking to verify it personally later. This is recorded in `deployment/acceptance-exceptions.json`; no full idle success is claimed. Offline timer boundary tests and the observed period remain evidence of their narrower checks.
