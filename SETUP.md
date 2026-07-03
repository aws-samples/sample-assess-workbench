# Setup Guide

How to deploy Assess Workbench into your own AWS account.

> This is the public setup guide. It assumes a single AWS account and the
> default AWS profile. Everything is driven by [Task](https://taskfile.dev).

## Prerequisites

1. **Python 3.13+** and **[uv](https://docs.astral.sh/uv/getting-started/installation/)**
2. **Node.js 18+** and **npm** (frontend)
3. **Terraform 1.5+**
4. **AWS CLI**, configured with credentials for your account
5. **AgentCore CLI:**
   ```bash
   uv tool install bedrock-agentcore-starter-toolkit
   ```
6. **Task** — the task runner that drives this guide. See the
   [install guide](https://taskfile.dev/installation/) for all options, or use
   one of:

   ```bash
   brew install go-task          # macOS (Homebrew)
   ```

   ```bash
   winget install Task.Task      # Windows
   ```

   ```bash
   npm install -g @go-task/cli   # cross-platform (uses Node.js from above)
   ```

Verify everything is installed:

```bash
task check:prereqs
```

## 1. Configure your environment

```bash
cp .env.example .env
# Edit .env: set AWS_REGION, PROJECT_NAME, and ENVIRONMENT.
# Leave AWS_PROFILE commented out to use your default AWS credentials.
```

`.env` is the single source for these values — they drive both the deploy
scripts and Terraform. Deploy one environment per AWS account; to run a second
environment (e.g. a separate prod), use a separate account.

**Deploying to another Region.** Set `AWS_REGION` and deploy — that's it. The
model IDs ship with the `global.` cross-Region inference prefix, which routes
from any commercial Region, so no model edits are needed to change Region. If
you need data residency (inference kept within one geography), swap `global.`
for your geography's prefix — `us.`, `eu.`, `au.`, `jp.` — in `.env` and in
`agents/<name>/agent.yaml` (each agent sets its own model). Not every model is
offered in every Region; check the model's "Regional availability" in the
Bedrock docs.

Verify your AWS credentials resolve:

```bash
task check:aws
```

## 2. Bootstrap the backend (one-time)

Terraform stores its state in an S3 bucket + DynamoDB lock table in your
account. Create them — plus the matching backend config — in one step:

```bash
task deploy:tf-bootstrap
```

This derives your account ID from your active credentials and:

- creates the S3 state bucket, DynamoDB lock table, and KMS key, and
- generates `terraform/backends/<env>.hcl` from the template, filling in your
  project name, account ID, and region — no manual editing.

The `<env>` matches your `ENVIRONMENT` value in `.env` (default `dev`), so the
deploy tasks select it automatically via `backends/${ENVIRONMENT}.hcl`. It's
idempotent — it skips resources that already exist and leaves an existing
backend config untouched, so it's safe to re-run.

> `backends/*.hcl` files are gitignored — they are specific to your account and
> are never committed. Only the template is tracked.

## 3. Deploy

```bash
task deploy
```

This runs the full sequence in order: shared memory → knowledge bases →
agents → Lambda layers → infrastructure → permissions → registry seed.
(`task deploy` also runs the bootstrap above for you, but doing it explicitly
first lets you confirm the backend before the full deploy.)

**What the deploy seeds.** It registers four example review agents —
Architecture, Security, Risk, and an Australian FSI Compliance example — and
loads one example standard (a fictitious "Acme Information Security Policy")
into the Standards Corpus. Treat both as starting points: manage the corpus
from the admin **Standards** page, and adapt or replace the agents to fit your
own domain and geography.

By default this **includes the hosted frontend** — `dev.tfvars` ships with
`deploy_frontend = true` and `enable_api_proxy = true`, so the deploy provisions
an S3 + CloudFront + WAF edge layer and uploads the SPA to it. See
[Frontend hosting](#frontend-hosting) below to access the hosted URL or to opt
out in favor of the local-only dev server.

For step-by-step control, run the sub-tasks individually — see
`task --list` for the full set (`deploy:memory`, `deploy:knowledge-bases`,
`deploy:agents`, `build:layers`, `deploy:infra`, `deploy:agent-permissions`,
`deploy:seed`, `deploy:user`).

## 4. Create a user and sign in

The deploy provisions the Cognito user pool but doesn't create any users, so
create your first sign-in:

```bash
task deploy:user  # prompts for email, password, and group
```

Then open the app at the CloudFront URL `task deploy` printed when it finished.
To reprint it (along with the API, WebSocket, and Cognito endpoints):

```bash
task status       # optional — endpoints + deployment status
```

Prefer to run the UI locally against the deployed backend?

```bash
task dev          # http://localhost:5173 (redirects to Cognito login)
```

## Testing

```bash
task test            # Python unit tests (no AWS needed)
task test:frontend   # Frontend unit tests
task test:live       # Live integration tests against your deployment
```

## Code quality

This repo uses [pre-commit](https://pre-commit.com/) for fast local hygiene
(ruff lint + format, eslint, terraform fmt, trailing-whitespace, end-of-file,
merge-conflict, and secret detection). A pre-push stage also runs the Python
unit tests and tflint before code is shared.

```bash
task precommit:install   # one-time: install the git hooks (pre-commit + pre-push)
task precommit           # run every hook against all files (same as CI)
```

## Teardown

```bash
task destroy         # Removes all AWS resources (with confirmation prompts)
```

The Terraform backend (state bucket + lock table) is preserved through
`destroy` so you can redeploy. Remove it manually if you want a clean slate.

## Frontend hosting

Frontend hosting is **on by default**: `dev.tfvars` sets `deploy_frontend = true`
and `enable_api_proxy = true`, so `task deploy` provisions an S3 + CloudFront +
WAF edge layer and serves the SPA (with the API reverse-proxied behind the same
origin). After a deploy, `task status` prints the CloudFront URL.

To rebuild and re-upload the SPA on its own (e.g. after a frontend change):

```bash
task deploy:frontend   # builds and uploads to S3, invalidates CloudFront
```

### Local-only frontend (opt out of hosting)

If you only want to run the frontend locally with `task dev` and skip the edge
layer entirely, set both flags to `false` in
`terraform/environments/<env>.tfvars` and redeploy:

```hcl
deploy_frontend  = false
enable_api_proxy = false
```

```bash
task deploy:infra      # tears down the edge layer
```

With hosting disabled, `task dev` runs the SPA at http://localhost:5173 against
the deployed backend API.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `task: command not found` | Install Task (see Prerequisites) |
| AWS credentials expired | Re-authenticate, then `task check:aws` |
| `SSM parameter not found` during `terraform apply` | Run `task deploy:agents` and the KB scripts first |
| `terraform init` fails on null provider | `cd terraform && terraform init -upgrade` |
| 401 on API calls | Cognito token expired — log in again |
| WebSocket disconnects | Idle timeout (~10 min) — refresh the page |
| View Lambda logs | `aws logs tail /aws/lambda/<project>-api-<env> --follow` |

## Configuration reference

### `.env`

| Variable | Purpose | Default |
|----------|---------|---------|
| `AWS_REGION` | AWS region | `us-west-2` |
| `ENVIRONMENT` | Environment name (selects tfvars + backend) | `dev` |
| `PROJECT_NAME` | Resource naming prefix | `assess-workbench` |
| `PYTHON_RUNTIME` | AgentCore Python runtime | `PYTHON_3_13` |
| `PLANNER_MODEL_ID` | Bedrock model for the review planner | see `.env.example` |
| `JUDGE_MODEL_ID` | Bedrock model for the quality judge | see `.env.example` |
| `IMAGE_ANALYSIS_MODEL_ID` | Bedrock model for image analysis | see `.env.example` |
| `GENERATOR_MODEL_ID` | Bedrock model for the standards-authoring helper (`scripts/generate_standard.py`); optional, not used by the deploy | see `.env.example` |
| `AWS_PROFILE` | AWS CLI profile (optional; omit for default) | — |

### `terraform/environments/<env>.tfvars`

Infrastructure settings (Lambda sizing, log retention, feature flags, Cognito
URLs). See the committed `dev.tfvars` for the full set with inline comments.
