# Session Handoff — 2026-03-11 (Session 11)

## Project Overview
- Instagram Reel -> Business Strategy Pipeline (FastAPI + Telegram bot + OpenRouter LLM)
- Ref: `CLAUDE.md` for full architecture, commands, execution rules

## Completed This Session

### 1. Frame resize for token reduction (commit `5c44aaa`)
- Changed keyframe scale from `1280:-2` to `512:-2` in `src/services/frames.py:33`
- Expected ~4x reduction in vision token usage

### 2. Relevance score calibration (commit `5c44aaa`)
- Added scoring guide to analysis prompt: 0.85-0.95 baseline since user pre-filters
- Updated relevance badge colors: green >= 0.85, yellow >= 0.70, red below

### 3. Markdown rendering in view.html (commit `5c44aaa`)
- `_md_to_html()` in plan_writer.py converts **bold**, *italic*, `code`, lists, line breaks
- Applied to task descriptions, summaries, insights, notes, deliverables

### 4. Real execution handlers (commit `14cc2d4`)
- `sales_script`: extracts section_id from tool_data or regex, calls update_section()
- `content` (meta_ads, email, social): saves drafts to plan/drafts/ directory
- `n8n`: saves workflow specs to plan/drafts/
- `claude_code`: logs for future Claude Code execution
- Added `tool_data` field to PlanTask model for structured automation data
- Updated plan prompt to instruct LLM to populate tool_data
- Dispatch table `_TOOL_HANDLERS` for clean routing

### 5. Coolify deploy fixed (commit `7ed9c6b`)
- Discovered Coolify API works with existing token
- Created `scripts/deploy.sh` — pushes to deploy branch + triggers Coolify API
- Set `manual_webhook_secret_github: reelbot-deploy-2026` via API
- No more manual SSH needed for deploys

### 6. Production deploy triggered
- Pushed 3 commits to main + deploy branches
- Coolify build queued (deployment: `u2ew7lk9mwhd7culyjlihwc0`)

## Tests
- 61 tests passing (up from 45 at start of session 9)

## Key Decisions
- **Coolify API for deploys** — `scripts/deploy.sh` replaces manual SSH workflow
- **Structured tool_data** in plans — LLM provides machine-readable data for automated execution
- **Handler dispatch table** — easy to add new tool handlers without modifying core logic

## Priority Next Steps

### 1. Verify production deploy succeeded
- Check deployment status via Coolify API
- Test health endpoint and process a reel to verify changes

### 2. GitHub webhook for auto-deploy
- Webhook secret is set (`reelbot-deploy-2026`)
- Need to configure GitHub webhook in repo settings pointing to Coolify webhook URL
- This would enable push-to-deploy without running deploy.sh

### 3. Test execution handlers end-to-end
- Approve one of the 11 review plans on production
- Verify sales_script handler works with real tool_data
- Check that content drafts get saved properly

### 4. Content execution improvements
- Code tasks (`claude_code`) are just logged — could integrate with Claude API for simple tasks
- Website/GHL tasks still need human intervention

## Context Notes
- Venv is at `venv/` (not `.venv/`)
- Deploy: `./scripts/deploy.sh` (or `bash scripts/deploy.sh`)
- Coolify API token: in master.env as COOLIFY_API_TOKEN
- Coolify app UUID: `l0g48c8g4wsskc40co4kssc8`
- Webhook secret: `reelbot-deploy-2026`
- 61 tests passing locally
