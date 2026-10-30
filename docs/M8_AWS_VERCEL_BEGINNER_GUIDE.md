# RepoGuide Milestone 8 — AWS + Vercel deployment from zero (2026)

This guide is written for the **Milestone 7 project plus the Milestone 8 differential patch**. It is a guided deployment *starter*, not a claim that your AWS account has already been configured. All cloud resources must be created under your AWS account. Follow sections in order; don't publish until local tests and costs are understood.

## 0. Deployment philosophy and your final running costs

**Desired final state**: Vercel hosts the static React UI; the API only consumes compute when requested; SQS stores work; Fargate worker service defaults to **desiredCount=0** and starts for indexing; Neon PostgreSQL Free can pause after idle; optional external Redis can pause/offer a small free plan; S3 stores small artifacts; all cloud administration is possible through a CLI or the admin UI. Your MacBook can be powered off.

### What “scale to zero” actually means

- **Lambda API**: you pay for actual invocations and duration, subject to AWS allowances and your account's plan. It has cold starts.
- **Fargate worker**: no task-compute charges with zero running tasks. The service, task definition, and images can remain deployed with no continuously running worker.
- **ECS activation**: first job or the admin wake button updates desired tasks to 1. The scheduled scaler checks queue depth (visible + in-flight) every five minutes. Two consecutive idle checks permit desiredCount=0. When the admin pauses processing, *new indexing requests fail*; read-only repo exploration still works.
- **Neon**: its free database compute pauses when unused, subject to account limits. Stored data stays. **Do not leave a pooler, recurring health query or MLflow background process holding DB connections.**
- **Persisting charges**: S3 object storage, CloudWatch logs/alarms, ECR image storage, DynamoDB and SQS usage, authentication, public IPv4 while a task runs, domain names, and other metered services may still cost money. A budget is a notification, **not a hard spending cap**. AWS new-customer credits are temporary.
- **Do not provision an ALB, NAT Gateway, EC2 VM, always-on RDS instance, RDS Proxy, or ElastiCache provisioned cluster** for this portfolio deployment. Their idle costs can dominate small workloads.

The deployed app is **authenticated/invite-only**, not open to anonymous users. This is deliberate: untrusted GitHub indexing, model tokens and CPU inference can cost money. Public marketing/portfolio content may link to a demo invitation or video while retaining a private app. Vercel Hobby is intended for personal noncommercial use; verify plan applicability if the project becomes commercial.

**AWS sign-up warning (October 2026)**: New accounts can receive up to $200 in credits under promotional terms, with limited Free-plan service access and an account expiry; verify your account's actual credit balance, supported services, and expiry. A Paid plan exposes more services but can bill beyond credits. You may need to upgrade before Fargate/ECS works. Don't infer eligibility from this guide.

### Backend service boundaries

```text
Browser (Vercel SPA)
     │  OAuth2 authorization code + PKCE (Cognito Hosted UI)
     ▼
API Gateway HTTP API (JWT signature, CORS, global throttling)
     │
Lambda container: FastAPI (read-only graph, source, dependencies;
                  on-demand grounded answer; submit indexing jobs)
     │             │                    │
     ├── Neon PostgreSQL/pgvector      ├── LLM + MCP HTTPS
     ├── Optional serverless Redis     └── SQS queue (index jobs)
     │                                       │
     └── DynamoDB job status                  ▼
                                      ECS Fargate worker
                                       1 vCPU, 4 GB RAM
                                        ├── git clone / parse / embed
                                        ├── PostgreSQL/pgvector
                                        ├── DynamoDB progress
                                        └── S3 job artifacts

EventBridge (every 5 min) -> Lambda queue scaler -> ECS desiredCount 0/1
CloudWatch -> logs, EMF metrics, alarms -> SNS email
GitHub Actions OIDC -> ECR immutable image pushes
Terraform -> AWS infrastructure as code
```

These are **two deployable backend microservices** with separate Docker images: API (Lambda) and background indexer (Fargate). We intentionally do **not** split every LangGraph node or retrieval channel into a separate network service. Those are modules within the API. Splitting them prematurely adds API latency, failure modes, security boundaries and idle costs without demonstrating useful scaling. Services have separate IAM roles and scaling models.

### Important AWS limitations

1. **API streaming:** the `POST /ask/stream` route is SSE under local Uvicorn. Standard FastAPI→Mangum→API Gateway HTTP API buffers its output. The M8 React production build disables the Stream toggle and uses the normal `/ask/robust` endpoint. True progressive AWS SSE requires a separate, streaming-capable REST API integration or Lambda Web Adapter/response-streaming handler. Don't claim it already works.
2. **Model cold starts:** your local SentenceTransformer embedding model, cross-encoder and MLflow dependencies make the Lambda container large. The first cold query may be slow or hit API Gateway’s request deadline even with models baked in the Docker image. First test `dense`/`hybrid` modes against one small repo; benchmark image import, model startup and query time. A warm-on-demand CPU inference ECS endpoint or a hosted embedding provider are future remedies, but will add cost or change stored vector compatibility. Keep embedding dimensionality at 384 until you explicitly migrate indexes.
3. **MLflow UI:** localhost:5000 no longer exists when your laptop is off. The deployed starter uses CloudWatch structured metrics/logs and retains your MLflow instrumentation in the code. MLflow **is disabled by default in AWS** until you configure an accessible, secured remote MLflow Tracking server. A real MLflow server, artifact store and SQL backend are separate infrastructure requiring authorization and storage; this patch does not claim they're deployed. The S3 artifacts bucket is ready for later MLflow use, but is currently used for completed job records.
4. **No local evaluation jobs in hosted demo**: `/api/ui/evaluation-jobs` returns 403 in AWS. Historical evaluation datasets and static reports remain readable; run live evaluations in GitHub Actions or an authorized isolated worker later.
5. **Single demo workspace:** authentication is mandatory, and the admin group controls indexing. Authorized reviewers share the indexed repository workspace. True multitenant ownership for repos, code, traces and feedback is a separate feature before unrestricted public signups.

---

## 1. Your MacBook: get the development system healthy first

Do **all of this before creating AWS infrastructure**. Nothing here incurs AWS compute charges.

Install Docker Desktop, Python/uv, Node/npm and git. You need an up-to-date AWS CLI v2 and Terraform for later phases. On macOS with Homebrew, typical installation commands:

```bash
brew install awscli node git uv
brew tap hashicorp/tap
brew install hashicorp/tap/terraform
```

Docker Desktop must be installed separately and opened. Test:

```bash
aws --version
terraform -version
docker version
node --version
uv --version
```

Apply the differential patch to your existing local RepoGuide checkout, then:

```bash
cd /path/to/RepoGuide
uv lock
uv sync --dev
cd frontend && npm install && npm run typecheck && npm run build && npm test
cd ..
uv run pytest -q tests/test_cloud.py
```

Commit `uv.lock` and `frontend/package-lock.json` along with the source patch. Both Docker builds use the frozen `uv.lock` to avoid silently changing package dependencies during deployment.

Bring up the *local Docker API plus local PostgreSQL and Redis*:

```bash
docker compose -f compose.yaml -f compose.m8.yaml up -d --build
curl http://127.0.0.1:8000/health
```

Run your frontend locally:

```bash
cd frontend
npm run dev
# open http://localhost:5173
```

This uses the original in-process local index worker. **It's fine for development**; AWS uses the durable SQS/Fargate path. Verify one public GitHub repo can be indexed and queried; check your GraphView null-target fix is still present.

Stop local Docker when done:

```bash
docker compose -f compose.yaml -f compose.m8.yaml down
# Do not add `-v` unless you intend to erase local Postgres volumes.
```

### Docker mental model

A **Dockerfile** describes an immutable image, a **container** is a process started from that image, **ECR** is a registry storing private images, **Lambda** runs an API image for each invocation, and **ECS Fargate** runs the heavy worker image without you maintaining EC2 virtual machines. Your Mac is used to build and upload images only; after the push, the cloud runs them.

---

## 2. AWS account, IAM and billing safety

1. Sign up at https://aws.amazon.com/free/; choose a plan appropriate for ECS availability and check whether it can consume your credits. In **Billing and Cost Management**, inspect your Free Tier and Credits panels.
2. Turn on **MFA** for the root account. Store recovery codes securely. Do not create root access keys.
3. Enable IAM Identity Center and assign yourself an administrator permission set for initial bootstrap, then use scoped permissions for everyday activity. For initial one-person learning, administrator is acceptable temporarily for Terraform; retire it after infrastructure stabilizes. Don't embed AWS keys in source or GitHub secrets.
4. Create a CLI SSO session via `aws configure sso` and follow its browser prompts. Choose your AWS account, the permission set and region `us-east-1`. Give the profile a name, e.g. `repoguide`.
5. Confirm:

```bash
export AWS_PROFILE=repoguide
export AWS_REGION=us-east-1
aws sso login --profile repoguide
aws sts get-caller-identity
```

`Account` in the output is your AWS account number. Check **the region** at the top-right of every AWS console page; resources in different regions won't show together.

6. Terraform includes an AWS Budgets $15/month notification and CloudWatch error alerts. Also set up the native AWS Free Tier usage/credit alerts in Billing. **A $15 budget is not an automatic kill switch**. Choose an even lower threshold as needed and inspect Cost Explorer after every major infrastructure change.

### What are IAM, roles and security groups?

**IAM** grants identities permissions to make AWS API calls: `sqs:ReceiveMessage`, `s3:PutObject`, etc. An **execution role** lets a service pull an image or write logs. A **task role** lets application code access its specific SQS queue, DynamoDB table and S3 prefix. Lambda has its own role for submitting jobs. Never put AWS access keys in the container.

A **security group** is a stateful firewall for network connections. The Fargate worker group has **no inbound rules**; only outbound HTTPS (`443`) and PostgreSQL (`5432`) are allowed. The worker receives messages by initiating outbound SQS requests, not by listening on a public port. Public subnet + Internet Gateway + assign public IP avoids a fixed NAT Gateway charge, but the public IPv4 address is charged while the task is running. Cloud API Lambda runs **outside** this VPC so it can reach Neon and LLM services without NAT.

### AWS region and budget

Use `us-east-1` consistently unless you have a reason to choose another region. Your **Neon DB region should ideally be geographically close** to Lambda and ECS for latency and network cost. Keep Vercel frontend location independent: browser → AWS HTTPS works globally.

---

## 3. Deploy frontend to Vercel first (to learn its final URL)

1. Push your RepoGuide Git repo to GitHub. The repo must **not** contain `.env`, `.env.deploy`, AWS credentials, Terraform state, provider tokens, or database passwords.
2. Create a Vercel account at https://vercel.com/ and select **Add New → Project → Import Git Repository**.
3. Select RepoGuide. Set **Root Directory = `frontend`**. Vercel should detect Vite. Use:
   - Framework: Vite
   - Build command: `npm run build`
   - Output directory: `dist`
   - Install command: `npm ci` (only once `frontend/package-lock.json` is committed)
4. Deploy. The first deployment may show *Cannot connect to API* because AWS does not exist yet. This is expected. Copy the final URL, e.g. `https://repoguide-demo.vercel.app`.
5. Add the environment variables from `frontend/.env.production.example` **later**, after Terraform outputs the real URLs. Vite variables beginning `VITE_` are visible to browsers and may contain only public URLs/client IDs—not API keys or database passwords.

Vercel Hobby is free for personal noncommercial use within its usage/fair-use limits. There is no need to run a Vercel compute function because your frontend is a static React SPA.

---

## 4. PostgreSQL that can pause: Neon

1. Sign up at https://console.neon.tech, create a small **PostgreSQL project** in an AWS-near region. Start on Free if it meets your expected storage/traffic limits.
2. Open SQL Editor and run:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
SELECT extversion FROM pg_extension WHERE extname = 'vector';
```

3. Copy the **TLS-enabled** connection string. SQLAlchemy expects the psycopg dialect, so use a URL beginning `postgresql+psycopg://`. Include `sslmode=require`. Use the Neon **pooled connection URL** for the short-lived Lambda workload where supported; test Alembic migrations against the direct URL if a pooler causes issues.
4. Create a *local, ignored* `.env.deploy` and set `DATABASE_URL=<your connection URL>` and at least `GEMINI_API_KEY=<value>`. Limit database credentials to the single demo workspace; do not reuse high-privilege credentials elsewhere.
5. After AWS secrets are configured (section 6), apply migrations **from your Mac once**, rather than having every Lambda cold start run migrations:

```bash
# Temporarily set DATABASE_URL to the Neon database; verify target before migration.
DATABASE_URL='postgresql+psycopg://...@.../...?sslmode=require' uv run alembic upgrade head
```

Alternatively export from `.env.deploy` using a safe local method; don't leave secrets in shell history. Run `alembic current` and verify `source_files`, `chunks`, `code_symbols` and relevant tables are present.

Neon Free's idle compute can suspend, but storage and service quotas still apply. A 1 GB database limit can fill quickly if you store full files, vector embeddings and many repos. Start with **one or two modest public repos**; measure their actual size.

### Alternative: AWS Aurora Serverless v2

Aurora PostgreSQL now supports **0 ACU auto-pause** on certain supported versions/regions; it still bills storage and has networking implications. If you switch later, create private subnets and SG rules permitting database port 5432 only from Lambda/ECS security groups. Lambda in private subnets would require an external-internet solution for Context7 and Gemini, such as NAT (which you want to avoid) or a carefully designed split between API and tool runners. Do not make Aurora publicly accessible to bypass these constraints. Do not add an RDS Proxy if you need Aurora to auto-pause. This patch deliberately deploys the cheaper Neon path first.

---

## 5. Terraform and ECR: create image registries first

Terraform is **infrastructure as code**: HCL `.tf` files describe resources; `terraform plan` computes intended changes; `terraform apply` calls AWS APIs to create/update them; state tracks resource IDs. State can contain sensitive data and must never be committed.

From the project root:

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`: set `aws_region`, `project`, `alert_email`, and **your exact Vercel `frontend_origin`**, without a trailing slash. Leave image URI placeholders for this bootstrap step. Use project name `repoguide-demo` consistently with the build script.

```bash
terraform fmt -recursive
terraform init
terraform validate
terraform plan
```

Read the plan carefully. Before the API/worker images exist, create ONLY the two ECR repositories:

```bash
terraform apply \
  -target=aws_ecr_repository.api \
  -target=aws_ecr_repository.worker
terraform output ecr_api
terraform output ecr_worker
```

Targeted apply is a **one-time bootstrap exception**. Normal deployments should use a complete `terraform plan` and `apply`.

ECR holds `repoguide-demo/api` and `repoguide-demo/worker` Docker images. Scan-on-push is enabled; tags are immutable. ECR storage has a small recurring cost even with no running compute.

---

## 6. Store credentials securely in AWS SSM Parameter Store

**SSM** is an AWS-managed service for configuration/secret parameters. We store a **single SecureString JSON object**, so the plaintext isn't embedded into the Terraform repository or state. This works for a small personal demo. For multi-tenant operations, use a more granular secrets strategy with rotation.

```bash
cd /path/to/RepoGuide
cat > .env.deploy <<'VALUES'
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST/DB?sslmode=require
GEMINI_API_KEY=REPLACE_ME
# Optional:
# REDIS_URL=rediss://...  (serverless managed Redis, verify provider limits)
# CONTEXT7_API_KEY=...
# GITHUB_PERSONAL_ACCESS_TOKEN=...
# JEV_API_KEY=...
VALUES
chmod 600 .env.deploy
```

Edit actual secrets only on your computer. Keep all deploy settings in this one file; no additions file is needed. Preview the local payload with `--dry-run`. To create or completely replace it, run:

```bash
uv run python scripts/update_runtime_settings.py \
  --env-file .env.deploy \
  --name /repoguide/demo/runtime
```

For later updates, edit `.env.deploy` and run the same command. It overwrites the complete JSON payload, including empty strings, and removes keys absent from your local file. There is no remote read, merge, or comparison. `--dry-run` works locally without AWS calls. Use `--profile` / `--region` or the AWS environment variables to select the account and region. The operator needs `ssm:PutParameter` and applicable KMS access. Use `--kms-key-id` for a custom key; otherwise AWS uses its default SSM key. See the root README for process restart behavior.

Verify in AWS **Systems Manager → Parameter Store**; the value is encrypted. Avoid printing the decrypted content. Terraform refers to the **parameter name** only. Application startup reads it with an IAM task or Lambda execution role. Use the default SSM encryption key for this starter; a custom customer KMS key needs an additional scoped `kms:Decrypt` policy.

If using Upstash or another hosted serverless Redis, place its **TLS `rediss://` URL** under `REDIS_URL` in the same parameter. **Don't create an always-on AWS ElastiCache cluster** solely for this demo.

---

## 7. Build Docker images and push them to ECR

From RepoGuide root, after you have committed your source changes (the image tag is based on `git rev-parse --short=12 HEAD`):

```bash
export AWS_PROFILE=repoguide
export AWS_REGION=us-east-1
export PROJECT=repoguide-demo
chmod +x scripts/aws_build_push.sh
./scripts/aws_build_push.sh
```

The script logs Docker into private ECR using an ephemeral authorization token; builds Linux/AMD64 images, important on Apple Silicon; uploads both images; and prints the **exact immutable URI** for each. Building may be slow and produce a large image because `sentence-transformers`, PyTorch, tree-sitter and MLflow dependencies are included. By default, the cloud Docker builds **bake the MiniLM embeddings model and cross-encoder weights into the image** so a Lambda cold start does not attempt a Hugging Face download; this increases image size/build time. If a model build/download fails, fix your model download access before deployment—avoid simply disabling preloading and relying on per-request downloads.

Inspect the ECR console to confirm that two images exist. Set their full URIs in `infra/terraform/terraform.tfvars`:

```hcl
api_image_uri    = "123456789012.dkr.ecr.us-east-1.amazonaws.com/repoguide-demo/api:YOUR_GIT_SHA"
worker_image_uri = "123456789012.dkr.ecr.us-east-1.amazonaws.com/repoguide-demo/worker:YOUR_GIT_SHA"
```

A future optimization is a **slim Lambda dependency image** that excludes training/data-ingestion libraries and uses a separately deployed embeddings microservice. Do not try to perform large ML-model downloads on every Lambda cold start in a production interview demo; load testing is mandatory.

---

## 8. Terraform: deploy the full AWS environment, step by step

From `infra/terraform`:

```bash
terraform validate
terraform plan -out=plan.tfplan
terraform show plan.tfplan
terraform apply plan.tfplan
```

Terraform creates these resources; inspect them in this order in the AWS Console:

| Service | AWS Console | Purpose | Check |
|---|---|---|---|
| ECR | Elastic Container Registry → Repositories | Private API/worker images | Both tags exist; scan findings reviewed |
| VPC | VPC → Your VPCs | Isolated worker networking | CIDR 10.88.0.0/16 |
| Subnets | VPC → Subnets | Two worker public subnets | Correct AZs and route table |
| Security groups | VPC → Security Groups | Firewall for Fargate | **No inbound rules**; outbound 443/5432 only |
| S3 | S3 → Buckets | Small job artifacts | Block Public Access=On; AES256; 30-day jobs lifecycle |
| DynamoDB | DynamoDB → Tables | Job state, pause flag, per-user rate limits | PAY_PER_REQUEST + TTL |
| SQS | Simple Queue Service → Queues | Main indexing queue + DLQ | 900s visibility, 3 attempts |
| ECS | Elastic Container Service → Clusters | Fargate worker manager | Service desired count **0** initially |
| Lambda | Lambda → Functions | API and scaler | x86_64 container image; roles; environment |
| API Gateway | API Gateway → HTTP APIs | HTTPS access to Lambda | JWT authorizer and CORS |
| Cognito | Cognito → User Pools | Login and read/write roles | No self-registration |
| CloudWatch | CloudWatch → Log Groups / Alarms | Error logs and alerts | Log retention=7d |
| EventBridge | Amazon EventBridge → Rules | Invoke scaler every five minutes | Rule enabled |
| Budgets | Billing → Budgets | Cost warnings | Confirm email |

### VPC and network walkthrough

- The VPC is your application's **logical private network**. AWS subnets are smaller IP ranges associated with particular Availability Zones. The worker sits in two public subnets for resiliency, with **no inbound firewall rule**.
- An Internet Gateway gives the task outbound Internet routing. Fargate is assigned a temporary public IP only while running (small hourly IP charge). No incoming HTTP server is exposed.
- DNS and outbound `443` are used to download GitHub code, reach AWS SQS/DynamoDB/S3, and contact models/documentation providers. `5432` connects to Neon with TLS.
- **No NAT Gateway** is created. Because the worker lives in a public subnet with an outbound-only SG and no inbound listeners, it can poll work without exposing an application port. Restrict the destination IP/CIDR further once you have a stable egress plan; arbitrary git clone or docs URLs remain risky inputs.

### IAM walkthrough

- **Lambda API role**: read the one specific SSM parameter; read/write *only the Jobs table*; `sqs:SendMessage` to the designated queue; describe and wake the designated ECS service; write logs.
- **ECS execution role**: pull ECR image and send logs to CloudWatch. It is not your application-data role.
- **ECS task role**: read the SSM parameter; receive/delete/change visibility on the designated SQS queue; update its job record; write to the S3 `jobs/` prefix.
- **Scaler Lambda role**: read queue length; update the control row; change worker desired count. It does *not* read database passwords.
- **Cognito tokens**: API Gateway validates their signature, issuer and audience before passing requests to FastAPI. Backend additionally checks `repoguide-admins` before indexing and worker controls. A valid browser token is not an AWS account key.
- **GitHub Actions role** (optional): trusts only your repo's `main` branch via OIDC, can push only to the two ECR repositories, and cannot deploy arbitrary infrastructure. Terraform updates remain manually reviewed initially.

### Basic monitoring

The backend emits structured CloudWatch EMF records with route families, request counts, 5xx counts and latency; requests and worker logs are also in 7-day CloudWatch log groups. AWS Lambda, SQS and ECS emit service metrics. Alarms notify you about repeated Lambda errors or messages in the DLQ. Confirm the SNS email subscription from your inbox.

CloudWatch Logs Insights example (select API log group):

```sql
fields @timestamp, @message
| filter @message like /ServerErrors/
| sort @timestamp desc
| limit 30
```

Do not enable full raw code/prompt capture or secrets in CloudWatch logs. For a real always-available MLflow UI, host the tracking server with authentication and a durable backend separately; then set `MLFLOW_ENABLED=true` and supply a reachable `MLFLOW_TRACKING_URI` to *both* API and worker. Do not set a localhost URI in deployed containers.

---

## 9. Cognito: create your admin account and reviewer accounts

Get Terraform outputs:

```bash
cd infra/terraform
terraform output api_url
terraform output user_pool_id
terraform output cognito_client_id
terraform output cognito_issuer
terraform output cognito_domain
```

Create your login with the **Cognito** console under User Pool → Users → Create user, or CLI:

```bash
POOL_ID=$(terraform output -raw user_pool_id)
aws cognito-idp admin-create-user \
  --user-pool-id "$POOL_ID" \
  --username 'YOUR_EMAIL' \
  --user-attributes Name=email,Value=YOUR_EMAIL Name=email_verified,Value=true
aws cognito-idp admin-add-user-to-group \
  --user-pool-id "$POOL_ID" --username 'YOUR_EMAIL' \
  --group-name repoguide-admins
```

The invitation flows through Cognito; the user sets their password. You are the **admin** and can start paid indexing. Create a reviewer/interviewer account similarly **without adding it to the admin group**. Reviewers can read/search/ask within your shared demo workspace but cannot submit indexing or wake paid worker tasks.

**Cost control**: an authenticated reviewer can still issue LLM requests. Lambda concurrency is capped at 2, expensive routes have a per-user per-minute DynamoDB counter, and API Gateway uses a global burst/rate ceiling. Those controls reduce exposure but do not guarantee an absolute spending cap.

---

## 10. Connect Vercel to API Gateway and Cognito

In your Vercel Project → Settings → Environment Variables, add the following public build-time values from Terraform output:

```text
VITE_API_BASE_URL=https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com
VITE_COGNITO_ISSUER=https://cognito-idp.us-east-1.amazonaws.com/YOUR_POOL_ID
VITE_COGNITO_CLIENT_ID=YOUR_PUBLIC_SPA_CLIENT_ID
```

These are **public identifiers and URLs**, not secrets. Configure Production and optionally Preview scopes; a Preview deployment URL must also be allowlisted in Cognito callbacks and API Gateway CORS before OAuth works. Avoid wildcards for a private demo.

Trigger **Redeploy** in Vercel because Vite injects environment variables at build time. Your final site redirects to Cognito Hosted UI, receives a code via OAuth2 PKCE, and attaches a short-lived JWT as `Authorization: Bearer` to API requests.

If Vercel URL changed from the original `frontend_origin`, update Terraform with the final exact origin and `terraform apply`. Do not put a trailing slash in `frontend_origin`, because Terraform adds it for callback URLs.

Open the site in an incognito browser. Without signing in, protected backend routes should return 401. After signing in, repository listing should work. An invited reviewer should get 403 for indexing. Admin can start an index job and see progress.

### Streaming in the hosted UI

The Stream checkbox is disabled in hosted mode and `POST /ask/robust` is used. Lambda HTTP API responses are buffered through the current Mangum adapter, even though Lambda and API Gateway **REST API** have streaming capabilities in newer AWS releases. Implement an explicit response-streaming handler and test end-to-end SSE before enabling this again.

---

## 11. First end-to-end cloud test

1. Open the API Gateway `api_url/health` URL: it should return `{"status":"ok"}`. The public health route does not read Postgres, so it is suitable for a basic network check.
2. Open Vercel, sign in with your new Cognito admin user.
3. Open **Overview** and verify API/Neon connectivity. If you haven't migrated or indexed the cloud database yet, the repo list will be empty.
4. Go to **Indexing**. Click **Wake worker** if the service is sleeping/paused. Note that Fargate startup can take minutes rather than seconds; you'll see actual counts, not fabricated progress.
5. Paste a **small public GitHub repository URL** and click **Index**. Expect DynamoDB status `queued → running → complete`; an SQS message is only deleted after the worker has committed results and written its S3 job summary.
6. Check the ECS service's Running Tasks, CloudWatch worker logs, DynamoDB Jobs table, and S3 `jobs/<uuid>.json` object. Inspect Postgres table counts.
7. Use Explorer, Graph, Dependencies and Ask. Verify citations link to real source lines.
8. Wait until SQS visible and in-flight counts are zero. After two scheduled idle scaler checks, ECS desired count should return to **0**.
9. Inspect AWS Billing and Cost Explorer the following day; AWS cost data may be delayed. Review alerts and clean up unused ECR images/artifacts.

### Debugging common failures

| Symptom | Likely cause | Where to inspect |
|---|---|---|
| Vercel login loops | Wrong callback origin, domain or OIDC variables | Cognito User Pool App Client + browser network |
| API returns 401 | Missing/expired JWT, wrong issuer or client ID | API Gateway JWT authorizer |
| Index says 403 | Signed in as reviewer, not admin | Cognito group membership and `cloud_guard.py` |
| Index says 503 paused | Worker intentionally paused | UI wake button / DynamoDB `control#worker` |
| Job remains queued | Fargate task cannot start or reach SQS | ECS events + task execution role + CloudWatch |
| Worker repeatedly retries | Git timeout, insufficient memory, missing model, database connection | Worker log group + SQS DLQ |
| Database operation times out | Neon suspended/invalid TLS URL, blocked 5432 | Lambda/worker logs, Neon dashboard |
| First Ask takes too long | Large Lambda import/ML model download or cold start | Lambda Duration/Init Duration, logs |
| No MLflow traces | AWS default has `MLFLOW_ENABLED=false` | CloudWatch works independently; remote MLflow needed |
| 429 from API | Deliberate global/per-user rate limit | CloudWatch API metrics |
| Hosting appears free but costs rise | Lingering public IPv4 task, S3/ECR images, logs, DB quotas | Cost Explorer by service and resource |

---

## 12. Spin up / spin down from the command line or UI

**UI**: On Indexing, authenticated admin can click **Wake worker** or **Sleep worker**. The sleep action refuses to stop tasks while jobs are pending or in flight. An idle scheduled scaler also returns desired task count to zero.

**CLI**: export Terraform outputs as env vars (replace values below):

```bash
export AWS_PROFILE=repoguide AWS_REGION=us-east-1
export REPOGUIDE_ECS_CLUSTER="$(terraform -chdir=infra/terraform output -raw ecs_cluster)"
export REPOGUIDE_ECS_SERVICE="$(terraform -chdir=infra/terraform output -raw ecs_service)"
export REPOGUIDE_QUEUE_URL="$(terraform -chdir=infra/terraform output -raw sqs_url)"
export REPOGUIDE_JOB_TABLE="$(terraform -chdir=infra/terraform output -raw job_table)"

uv run python scripts/cloud_control.py status
uv run python scripts/cloud_control.py wake
uv run python scripts/cloud_control.py sleep
```

**Sleep does not destroy data or turn off Lambda/API Gateway/Vercel.** It pauses indexing compute; users can still ask questions, and the Lambda embedding computation still incurs per-invocation charges. If you want a completely frozen site during the week, disable invitations and block API routes or temporarily lower Lambda reserved concurrency while retaining a static Vercel landing page.

When an interview is coming, `wake` is enough to prestart an index worker. **For query latency**, test the Lambda app and cached models separately; waking a queue worker doesn't warm the Lambda's embedding model.

---

## 13. GitHub Actions CI/CD and deployment changes

The patch adds `.github/workflows/m8-containers.yml`. It compiles/pushes two immutable Docker images with your code SHA. It uses GitHub OIDC to obtain short-lived AWS credentials rather than stored AWS secret keys.

Optional setup in Terraform:

```hcl
github_oidc_subject = "repo:YOUR_OWNER/RepoGuide:ref:refs/heads/main"
```

**Important**: GitHub's OIDC `sub` format can differ for new organizations/repositories, including ID-qualified owner/repo names. The example above is only the older form; consult GitHub's current OIDC claims for *your* repository, then set `github_oidc_subject` to the exact claim for the `main` branch. Do not weaken the trust to `repo:*` or use a wildcard. A mismatch causes `AssumeRoleWithWebIdentity` to fail.

After `terraform apply`, copy `github_ecr_role_arn` to GitHub Repository → Settings → Secrets and variables → Actions → Variables as `AWS_ECR_ROLE_ARN`. Also define `AWS_REGION=us-east-1` and `AWS_PROJECT=repoguide-demo`. The OIDC trust is restricted to your exact `main` branch. Do not run untrusted pull-request code with cloud deploy permissions.

**Build/push is deliberately separate from infrastructure apply.** A successful ECR push does not automatically replace production Lambda or ECS tasks. Review the new image hash, update Terraform `api_image_uri`/`worker_image_uri`, and run `terraform plan`/`apply` yourself. Later, once tests are reliable, you can automate staged deployments with checks and rollback.

The previous M6 quality/evaluation GitHub Actions workflows remain in the project. Keep CI deterministic tests on every PR; run costly LLM/MCP evaluations on a schedule or manual trigger.

---

## 14. Security checklist before sharing invitations

- Cognito self-signup disabled; admin only creates users. Test reviewer cannot index or control Fargate. Do not share your own admin account.
- API Gateway JWT authorizer enabled on all routes except GET `/health`; CORS lists explicit frontend origins.
- No `.env`, database URL, Gemini tokens, Terraform state or `frontend` secrets committed. Use SSM SecureString and IAM roles. SSM values should be rotated if accidentally exposed.
- S3 bucket fully private and encrypted; SQS encrypted; ECR image scanning reviewed. Remove old vulnerable images; freeze dependencies with lockfiles.
- Fargate task has no inbound ports, is non-root, and has a small egress policy. Git clone is constrained by the existing URL validator, shallow clone and timeout; **this is not a substitute for an adversarial sandbox**. Enforce repository size, file-size, memory, CPU, and egress budgets; restrict public indexing to your admin account.
- Lambda global concurrency=2, per-user expensive-request counter, API Gateway throttle. Add account-level LLM/provider spending alerts as well; rate limiting is not a billing cap.
- DynamoDB TTL clears job metadata after seven days; CloudWatch logs retained seven days; S3 `jobs/` objects expire after 30 days. Audit other source snapshots/MLflow traces for privacy.
- Evaluations that execute arbitrary prompts or clone public repos are admin/CI-only. MLflow feedback currently needs a secure remote tracking server and per-user trace ownership before publicly enabling it.
- Monitor the DLQ and Lambda errors. Update container base images and dependencies regularly; scan for secrets with GitHub security features.

---

## 15. Billing cleanup and rollback

**No running local processes is necessary after deployment.** Closing your MacBook won't stop Vercel, Lambda, SQS, or a started Fargate worker. Fargate returns to zero via the scheduled scaler when its queue is idle.

Before a long break:

```bash
uv run python scripts/cloud_control.py sleep
aws ecs describe-services --cluster "$REPOGUIDE_ECS_CLUSTER" \
  --services "$REPOGUIDE_ECS_SERVICE" --query 'services[0].[desiredCount,runningCount]'
```

To destroy cloud resources and stop most ongoing AWS costs:

```bash
cd infra/terraform
terraform plan -destroy
terraform destroy
```

**Warning**: destroying also removes the DynamoDB status table, SQS queues, Cognito accounts, S3 bucket (if empty; Terraform won't delete nonempty buckets by default), ECR repos (if empty), VPC, Lambda and ECS infrastructure. Back up data first. Neon, Upstash and Vercel are outside Terraform; remove them separately when no longer needed. Terraform state is local and must be backed up securely; consider moving it to an encrypted S3 remote backend once the deployment is stable.

### What has and has not been verified

The M8 patch's Python files compile, and small isolated API/worker authentication tests run locally. It was built as an additive diff against the uploaded project plus M6/M7 patches. A real Terraform `plan`, container build, registry push, authenticated Cognito sign-in, AWS Fargate lifecycle, and live end-to-end provider test have **not** been executed by the assistant in your AWS account. You must run those checks in order and capture the failure logs if a specific cloud integration requires adaptation.
