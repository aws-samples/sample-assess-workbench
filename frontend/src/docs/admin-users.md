# User Management

> Admin access required

## Authentication

The application uses Amazon Cognito for authentication. Users sign in with
email and password via the Cognito Hosted UI. All API requests require a valid
JWT token.

There is **no public self-registration** — the user pool is configured with
`allow_admin_create_user_only`. New accounts are created by an admin (see
[Adding Users](#adding-users) below).

## Roles

Access is driven by Cognito group membership. Every authenticated user resolves
to exactly one role (admin wins if multiple groups are present):

| Group | Role | Capabilities |
|-------|------|--------------|
| `admins` | Admin | Full write, plus agent registry, standards, and guardrail-event management |
| `users` | User | Their own projects only — create, review, chat, delete |
| `viewers` | Viewer | Full read (sees everything an admin sees) but **zero write** |

A user with no recognized group falls back to **viewer** (least-privilege). When
OIDC federation is enabled, federated users are auto-assigned to `viewers`,
which is what makes them read-only.

Admin-only pages (Benchmarks, Agent Registry) are **readable** by admins and
viewers; only admins can change them. The `users` role cannot see those pages.

## Adding Users

The supported way to create an account is the deploy task, which sets a
permanent password and assigns a group in one step:

```bash
task deploy:user
```

It prompts for an email, a password (or generates one), and a group, then
creates the user with the email verification suppressed — no temporary-password
reset on first login.

To create a user manually in the AWS Console instead:

1. Open the AWS Console → Cognito → User Pools
2. Select your user pool (named `<project_name>-users-<environment>`)
3. Click **Create user**, enter their email, and choose how to set the password
4. Add them to a group (see below)

## Managing Group Membership

1. In the Cognito console, open the user pool and select the user
2. Under **Group memberships**, click **Add user to group** (or remove)
3. Pick `admins`, `users`, or `viewers`
4. The user must sign out and back in for the change to take effect in their JWT
