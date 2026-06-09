# Deployment Architecture

How code and configuration get from a developer's laptop into a running application. This file explains the deploy pipeline structure; the step-by-step operator runbook is `DEPLOYMENT.md` at the repo root.

> **Last verified:** 2026-04-21 against `Taskfile.yml`, `scripts/`, and `terraform/` (including `terraform/modules/edge/`). Re-verify when adding a new deploy step, a new script, or a new cross-stack handoff.
