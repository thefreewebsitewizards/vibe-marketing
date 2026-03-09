# Session Handoff — 2026-03-09 (Session 6)

## Project Overview
- Instagram Reel → Business Strategy Pipeline (FastAPI + Telegram bot + OpenRouter LLM)
- Ref: `CLAUDE.md` for full architecture, commands, execution rules

## Completed This Session

### 1. Shared cross-project context system (commit `e6337f8`)
- Created `~/projects/openclaw/.shared-context/` with 10 project status files
- `src/utils/shared_context.py`: loader reads from local dev path, Docker bundled path, or repo-relative fallback
- Both prompts (`analyze_reel.py`, `generate_plan.py`) now dynamically load business context from shared files instead of hardcoded text
- Global rule in `~/.claude/rules/standards.md` tells every Claude session to update its context file after changes
- User ran bootstrap prompt in all project terminals — all 10 files populated

### 2. Bundled shared context for production (commit `ea7b1d8`)
- `shared-context/` directory in repo, `COPY`'d in Dockerfile
- Pre-push git hook (`.git/hooks/pre-push`) auto-syncs `~/.shared-context/*.md` → `shared-context/` and commits before push
- Production Docker reads from `/app/shared-context/` when local path unavailable

### 3. Cost breakdown page (commit `e6337f8`)
- New `/costs` route in `src/routers/dashboard.py` with `static/costs.html` template
- Shows: total estimated vs actual cost, total tokens, cost-by-step bar chart, per-plan cost rows with colored step pills
- Dashboard "Total Cost" stat is clickable → links to `/costs`
- Plan view "Cost Breakdown" header links to `/costs` too

### 4. Proportional analysis / over-analysis fix (commit `e6337f8`)
- Analysis prompt: "MATCH DEPTH TO COMPLEXITY" — simple videos get short analysis
- Plan prompt: 1 task for simple things (e.g., "install this skill"), prefer 1-2 tasks, explicit bad example added
- Plan prompt: tasks should name which specific project they apply to (rule 6)

## Key Decisions
- Pre-commit hooks can't modify commits (git limitation) — used pre-push hook instead
- Shared context bundled in repo (not volume mount) so production works when local machine is off
- Other projects read `.shared-context/` on-demand (lazy); only ReelBot injects it into every LLM call

## Priority Next Steps

### 1. Continue training calibration
- User needs to rate the 5 resent plans in Telegram (feedback buttons sent last session)
- After rating, send a NEW reel to test improved prompts + shared context
- Compare before/after quality

### 2. Consider removing repurposing + personal brand plans
- Each adds ~$0.04 cost per reel
- User questioned their value last session

### 3. Keep shared context files fresh
- When projects change significantly, their `.shared-context/*.md` files should be updated
- Pre-push hook handles syncing to reelbot repo automatically

### 4. Fix root-owned .env files (carried over)
- `/home/gamin/projects/openclaw/.env` and `claude-code-projects/tfww/.env` may need `chown`

## Deploy Quick Reference
```bash
cd ~/projects/openclaw/claude-code-projects/reelbot
git push origin main && git push origin main:deploy
COOLIFY_TOKEN=$(grep '^COOLIFY_API_TOKEN=' .env | cut -d= -f2 | tr -d '"' | tr -d "'" | tr -d '\r')
ssh root@76.13.29.110 "curl -s -X POST http://localhost:8000/api/v1/applications/l0g48c8g4wsskc40co4kssc8/restart -H 'Authorization: Bearer $COOLIFY_TOKEN' -H 'Content-Type: application/json'"
```

## Context Notes
- Telegram bot token in .env has Windows line endings — always `tr -d '\r'` when extracting
- Pre-push hook is in `.git/hooks/pre-push` (not tracked by git — recreate if repo is re-cloned)
- Shared context loader priority: `~/projects/openclaw/.shared-context/` → `/app/shared-context/` → `./shared-context/`
