# Edge Module: S3 + CloudFront + WAF

Optional child module of the main Terraform stack. Controlled by the parent's
`deploy_frontend` variable (defaults to `false`).

## When to use

- **Prod / staging:** always. Set `deploy_frontend = true` in your tfvars.
- **Dev:** optional. Use `task dev` to run the Vite dev server at
  `http://localhost:5173` for day-to-day development. Enable this module in
  dev only when you want to exercise the hosted flow end-to-end (testing,
  demos, verifying a change to CloudFront/WAF config).

## How it wires into the parent

The parent passes `project_name`, `environment`, `aws_region`,
`cognito_hosted_ui_url`, `log_retention_days`, and `price_class` as inputs.
The module outputs `frontend_url`, `bucket_name`, and
`cloudfront_distribution_id`. The parent composes the frontend URL into
`cognito_callback_urls`, `cognito_logout_urls`, and `allowed_origins`
automatically — no manual tfvars edits required.

When `deploy_frontend = false`, the module is not instantiated and all
edge-related outputs are empty strings.

## Deploying the frontend

```bash
# 1. Ensure deploy_frontend = true in your tfvars, then apply infra.
ENVIRONMENT=<env> task deploy:infra

# 2. Build the SPA and upload it to S3 (with CloudFront invalidation).
ENVIRONMENT=<env> task deploy:frontend
```

On subsequent code changes, only step 2 is needed. The CloudFront URL is
stable across re-applies.

## Architecture

- S3 bucket in `var.aws_region` holds the built SPA assets. Private bucket,
  CloudFront Origin Access Control is the only reader.
- CloudFront distribution in `us-east-1` (required for CloudFront). Serves
  the SPA over HTTPS with SPA routing (403/404 → `/index.html`), security
  headers (CSP, HSTS, X-Frame-Options, etc.), and per-path cache policies.
- `index.html` and `config.json` use `CachingDisabled` so they're always
  fresh; content-hashed assets use `CachingOptimized`.
- WAFv2 WebACL attached: AWS managed common rules + known-bad-inputs rules
  + 2000-req/5-min per-IP rate limit.
- `force_destroy` on the S3 bucket is `true` only in dev — staging/prod
  buckets are protected from accidental `terraform destroy`.

## Provider requirements

This module requires two AWS provider configurations passed from the parent:
- `aws` (default) — for S3 resources in the application region
- `aws.us_east_1` — for CloudFront, response headers policy, and WAFv2
  (CloudFront scope must be declared in us-east-1)
