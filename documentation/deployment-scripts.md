# Writing Deployment Scripts

The convention every script that touches AWS or Terraform must follow: resolve
the environment through a single helper so a command can never silently run
against the wrong account. For the deploy pipeline these scripts drive, see
[`deployment-architecture.md`](deployment-architecture.md).

## Resolve the environment through `with-env.sh`

At the top of any script that runs an AWS or Terraform operation, source the
helper and assert what you need:

```bash
# shellcheck source=scripts/utils/with-env.sh
source scripts/utils/with-env.sh
: "${PROJECT_NAME:?}"
```

`scripts/utils/with-env.sh` loads `.env`, lets a per-command override
(`ENVIRONMENT=demo task …`, `PROJECT_NAME=… AWS_REGION=… task …`) win over the
file, and guards against running in the wrong AWS account.

Do **not** `source .env` by hand and do **not** default the tenant knobs
(`${ENVIRONMENT:-dev}`) — a pre-commit hook
(`scripts/utils/check_env_resolution.sh`) rejects both.

See the `with-env.sh` header for the full contract; `scripts/destroy_ssm.sh` is
a short reference example.
