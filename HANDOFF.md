# Session Handoff — 2026-03-11 (Session 12)

## Project Overview
- Instagram Reel -> Business Strategy Pipeline (FastAPI + Telegram bot + OpenRouter LLM)
- Ref: `CLAUDE.md` for full architecture, commands, execution rules

## Completed This Session

### E2E execution tested and verified:
- Approved a local plan → executor thread fired in background
- Auto task (sales_script) ran and completed via handler
- Human tasks correctly flagged as `needs_human`
- External agent flow tested: `PATCH /plans/{id}/tasks/{index}` updates execution log
- n8n webhook fired on approval (`N8N_EXECUTION_WEBHOOK`)
- Plan status transitions: review → approved → in_progress (correct lifecycle)

### GitHub Actions auto-deploy:
- Created `.github/workflows/deploy.yml` — triggers Coolify build on push to main
- Coolify branch updated from `deploy` → `main` (no more deploy branch needed)
- `COOLIFY_API_TOKEN` added as GitHub repo secret
- Deploy script updated to push to `main` instead of `main:deploy`
- Workflow: push to main → GitHub Action → Coolify API → build + poll + health check

### OpenClaw/n8n integration:
- `N8N_EXECUTION_WEBHOOK=https://n8n.leadneedleai.com/webhook/plan-approved` set in master.env + .env
- On plan approval, ReelBot POSTs `{reel_id, plan_dir}` to n8n webhook
- Verified webhook fires in e2e test

### Previous session work (still deployed):
- Execution handlers: sales_script (auto), content drafts (auto), n8n specs (auto)
- Task-level API for agents: GET /plans/{id}/tasks, PATCH /plans/{id}/tasks/{index}
- Actual costs resolved from OpenRouter before writing plan artifacts
- 61 tests passing

## Execution flow for Claude Code / OpenClaw:
```
1. GET /plans/approved → list approved plans
2. GET /plans/{id}/tasks → get tasks with status
3. For each pending task:
   - Read tool_data for structured instructions
   - Execute (update script section, write code, create content)
   - PATCH /plans/{id}/tasks/{index} with {status: "completed", notes: "..."}
4. Plan auto-completes when all auto tasks are done
```

## Priority Next Steps

### 1. Deploy and test in production
- Push to main to trigger first GitHub Actions deploy
- Approve one of the 11 review plans on production
- Verify n8n receives webhook POST

### 2. Create n8n workflow for plan-approved webhook
- Webhook trigger at `https://n8n.leadneedleai.com/webhook/plan-approved`
- Should route to OpenClaw (Discord notification or direct execution)
- Payload: `{reel_id, plan_dir}` → fetch tasks → dispatch

### 3. Production monitoring
- Check execution logs after approval
- Verify Telegram notifications work for human tasks

## Context Notes
- Deploy: `./scripts/deploy.sh` or just push to main (GitHub Actions)
- Coolify app UUID: `l0g48c8g4wsskc40co4kssc8`, branch: `main`
- n8n webhook: `https://n8n.leadneedleai.com/webhook/plan-approved`
- 61 tests passing locally
