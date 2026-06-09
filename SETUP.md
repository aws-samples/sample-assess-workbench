# Setup Guide

How to deploy the AgentCore Risk Assessor into your own AWS account.

> This is the public setup guide. It assumes a single AWS account and the
> default AWS profile. Everything is driven by [Task](https://taskfile.dev).

## Prerequisites

1. **Python 3.13+** and **[uv](https://docs.astral.sh/uv/getting-started/installation/)**
2. **pip** (used by the Lambda layer build scripts)
3. **Node.js 18+** and **npm** (frontend)
4. **Terraform 1.5+**
5. **AWS CLI**, configured with credentials for your account
6. **AgentCore CLI:**
   ```bash
   uv tool install bedrock-agentcore-starter-toolkit
   ```
7. **Task:**
   ```bash
   brew install go-task                              # macOS
   sh -c "$(curl -L https://taskfile.dev/install.sh)" -- -d -b /usr/local/bin   # Linux
   winget install Task.Task                          # Windows
   ```

Verify everything is installed:

```bash
task check:prereqs
```

## 1. Configure your environment

```bash
cp .env.example .env
# Edit .env: set AWS_REGION and PROJECT_NAME.
# Leave AWS_PROFILE commented out to use your default AWS credentials.
```

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
agents → Lambda layers → infrastructure → permissions → registry seed. The
final user-creation step is interactive (prompts for an email). (`task deploy`
also runs the bootstrap above for you, but doing it explicitly first lets you
confirm the backend before the full deploy.)

By default this **includes the hosted frontend** — `dev.tfvars` ships with
`deploy_frontend = true` and `enable_api_proxy = true`, so the deploy provisions
an S3 + CloudFront + WAF edge layer and uploads the SPA to it. See
[Frontend hosting](#frontend-hosting) below to access the hosted URL or to opt
out in favor of the local-only dev server.

For step-by-step control, run the sub-tasks individually — see
`task --list` for the full set (`deploy:memory`, `deploy:knowledge-bases`,
`deploy:agents`, `build:layers`, `deploy:infra`, `deploy:agent-permissions`,
`deploy:seed`, `deploy:user`).

## 4. Run it

The default deploy hosts the frontend on CloudFront. Get the URL:

```bash
task status       # prints HTTP API, WebSocket, Cognito, and frontend URLs
```

Or run the frontend locally against the deployed backend:

```bash
task dev          # http://localhost:5173 (redirects to Cognito login)
```

Create a login:

```bash
task deploy:user  # prompts for email, password, and group
```

## Testing

```bash
task test            # Python unit tests (no AWS needed)
task test:frontend   # Frontend unit tests
task test:live       # Live integration tests against your deployment
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
| `PROJECT_NAME` | Resource naming prefix | `risk-assessor` |
| `PYTHON_RUNTIME` | AgentCore Python runtime | `PYTHON_3_13` |
| `PLANNER_MODEL_ID` | Bedrock model for the review planner | see `.env.example` |
| `JUDGE_MODEL_ID` | Bedrock model for the quality judge | see `.env.example` |
| `IMAGE_ANALYSIS_MODEL_ID` | Bedrock model for image analysis | see `.env.example` |
| `AWS_PROFILE` | AWS CLI profile (optional; omit for default) | — |

### `terraform/environments/<env>.tfvars`

Infrastructure settings (Lambda sizing, log retention, feature flags, Cognito
URLs). See the committed `dev.tfvars` for the full set with inline comments.
