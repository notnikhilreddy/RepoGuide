> Historical initial-release record. The current improvement release, authorization, scope and verification status are tracked in [product-release.md](product-release.md) and [IMPROVEMENT_STATUS.md](../IMPROVEMENT_STATUS.md). The earlier evaluation/idle deferrals do not authorize a new skipped quality gate.

# Cost estimate — Ohio, November 5, 2026

The owner's **less-than-$10 AWS validation budget** covers this rollout. No paid comparative evaluation is running. Costs below are estimates; same-day Cost Explorer still reports $0 and billing is delayed, so this does not establish a zero-cost deployment or settled bill.

The [AWS Ohio regional price list](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonECS/current/us-east-2/index.json), checked November 5, reports Linux/x86 Fargate prices of **$0.04048/vCPU-hour** and **$0.004445/GiB-hour**. Public IPv4 adds approximately $0.005/hour per running task ([VPC pricing](https://aws.amazon.com/vpc/pricing/)). The included 20 GB ephemeral disk is sufficient; no extra ephemeral allocation, NAT gateway, ALB, EC2, RDS, ElastiCache or always-on MLflow server is deployed.

| Task | Compute plus one IPv4/hour | 32.5 hours/month | 730 hours/month |
| --- | ---: | ---: | ---: |
| Selected: 1 vCPU / 2 GiB | **$0.05437** | **$1.77** | **$39.69** |
| Measured baseline: 1 vCPU / 4 GiB | $0.06326 | $2.06 | $46.18 |

These rates are per worker. The owner cancelled the real idle acceptance test after **15.3 minutes**, and both workers were stopped. That partial observation costs approximately **$0.028** in compute/IPv4, plus startup/stop overhead, images, requests and logs. It does not establish full idle shutdown/reset acceptance. Earlier sizing, browser and recovery runs add bounded runtime. This is far below $10 at the observed scale, but an estimate is not a hard spending limit.

Five minutes of daily work followed by 60 idle minutes means about **32.5 task-hours/month**, not 2.5. Explicit Drain & stop after work lowers cost. Continuous accepted work can keep a worker on indefinitely; rolling idle shutdown is not a lifetime cap. Both services must converge to desired/running/pending zero after acceptance. Static storage, API requests and external services can still cost money at zero workers.

## Image and artifact retention

Published compressed image sizes are **545,305,543 bytes Answer** and **480,218,210 bytes Index**. Four retained digests per role currently sum to approximately **4.10 GB** before layer deduplication; a conservative storage estimate at $0.10/GB-month is about **$0.41/month** for that sum. Shared identical layers reduce physical storage. Do not multiply uncompressed local sizes to claim an ECR bill. Retain current and rollback digests; untagged images expire after seven days, tagged releases require explicit retention review.

S3 is private, encrypted and versioned. Job artifacts expire after 30 days; release evidence is retained separately. CloudWatch logs expire after seven days. API Gateway/Lambda, DynamoDB/SQS, Cognito, CloudWatch alarms and transfer add usage-dependent charges. Free tiers, credits and account-wide usage affect the bill and are not treated as guaranteed savings.

The Terraform budget remains **$15/month**, with $5 actual and $10 forecast early notifications, as an account warning rather than authorization to spend that amount. The stricter rollout budget remains below $10. AWS Budgets are delayed alerts, not caps. The SNS email subscription currently awaits owner confirmation; do not assume alarm emails are deliverable until confirmed. Check the final monitoring evidence for the latest state.

## Model and external services

OpenAI standard short-context pricing for `gpt-6-luna` is **$0.10/M input, $0.50/M output and $0.01/M cached input**, checked against [official model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna). A representative functional answer used 2,967 input and 575 output tokens: approximately **$0.000584** before any applicable taxes, with no cached-input discount assumed. Hosted smoke tests send only a handful of functional requests; there is no judge/comparative-evaluation loop. Standard service tier, low reasoning effort, 2,000 maximum output tokens and bounded input constrain calls.

Existing Neon, Upstash and Vercel are reused without creating duplicates or upgrading plans. Upstash is optional and fails open to a cache miss. GitHub MCP is disabled; Context7 uses the existing configuration. Future evaluations, Actions storage/runtime, larger repositories, Vercel/Neon/Upstash quotas and external model usage require separate cost review.

After AWS billing settles, compare Cost Explorer service line items and ECS task lifetimes against this estimate, record credits separately, and investigate any running task or unattached public IPv4. No settled actual total is claimed in this document.
