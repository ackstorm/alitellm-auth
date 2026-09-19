---
name: deploy-runbook
description: Production deploy checklist. Use when deploying any service to production, cutting a release, or when someone asks about the deploy process.
---

# Deploy runbook

This skill was delivered by the organization server, not installed locally.
If you can read this, org-managed skill distribution works.

## Before deploying

1. Confirm the change is merged to `dev` and CI is green.
2. Check the on-call rota — never deploy without a second pair of eyes.
3. Announce in the deploy channel with the release tag.

## Deploy

1. Tag the release: `vMAJOR.MINOR.PATCH`, semantic versioning.
2. Watch the rollout for 10 minutes before declaring success.
3. Post the release notes link in the channel.

## Rollback

If error rate rises above baseline, roll back first and investigate afterwards.
A rollback is never a failure — a prolonged outage is.
