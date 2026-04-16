---
task_id: 06
title: "Configure Alertmanager SMTP credentials"
type: task
agent: "deploy-checker"
phase: 1
depends_on: [1]
status: "pending"
priority: "high"
board: "[[production-deployment/README]]"
files: ["monitoring/alertmanager.yml"]
tags:
  - task
  - alerting
  - infrastructure
  - deployment
---

# Task 06: Configure Alertmanager SMTP credentials

## Objective
Replace the placeholder SMTP credentials in `monitoring/alertmanager.yml` with real values so alerts are delivered to the on-call email.

## Context
Task 05 (customer launch fixes) created the Alertmanager pipeline but left placeholder credentials because Alertmanager does not support env-var substitution in its config file.

## Files to Modify
- `monitoring/alertmanager.yml` — on the production server only (config is gitignored or kept as-is in repo with placeholders)

## Acceptance Criteria
- [ ] `smtp_smarthost` is set to a real SMTP relay host:port (e.g., `smtp.gmail.com:587`)
- [ ] `smtp_from` is a valid sender email (e.g., `alerts@tradeready.io`)
- [ ] `smtp_auth_username` is the SMTP login
- [ ] `smtp_auth_password` is the SMTP password or app-password (never committed)
- [ ] `to:` under `email_configs` is the real on-call email address
- [ ] Test alert delivered successfully (fire a test alert and verify email arrives)

## Dependencies
Task 01 — code must be pulled so `monitoring/alertmanager.yml` is present.

## Agent Instructions
1. Open `monitoring/alertmanager.yml` on the production server
2. Replace these four placeholder values:
   - `smtp_smarthost: REPLACE_WITH_SMTP_HOST` → real host:port
   - `smtp_from: REPLACE_WITH_SENDER` → real sender
   - `smtp_auth_username: REPLACE_WITH_USERNAME` → real username
   - `smtp_auth_password: REPLACE_WITH_APP_PASSWORD` → real password (use Gmail app password if Gmail)
   - `to: oncall@yourdomain.com` → real on-call email
3. File permissions: `chmod 600 monitoring/alertmanager.yml` (contains credentials)
4. After Alertmanager starts, fire a test alert:
   ```
   curl -XPOST http://localhost:9093/api/v2/alerts \
     -H 'Content-Type: application/json' \
     -d '[{"labels":{"alertname":"TestAlert","severity":"warning"}}]'
   ```
5. Verify the test email arrives

## Estimated Complexity
Medium — config editing plus SMTP setup/testing
