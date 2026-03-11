# Session Handoff — 2026-03-10 (Session 10)

## Project Overview
- Instagram Reel -> Business Strategy Pipeline (FastAPI + Telegram bot + OpenRouter LLM)
- Ref: `CLAUDE.md` for full architecture, commands, execution rules

## Completed This Session

### 1. Frame resize for token reduction
- Changed keyframe scale from `1280:-2` to `512:-2` in `src/services/frames.py:33`
- Kimi was using 35,859 prompt tokens vs Gemini's 7,868 for the same reel — oversized base64 frames were the cause
- Expected ~4x reduction in vision token usage (and proportional cost savings)

### 2. Relevance score calibration
- Added scoring guide to analysis prompt in `src/prompts/analyze_reel.py` (reel + carousel templates)
- New calibration: 0.95-1.0 = directly actionable today, 0.90-0.94 = implement this week, 0.85-0.89 = useful with adaptation, 0.80-0.84 = tangentially relevant, below 0.80 = genuinely off-topic
- Reasoning: user pre-filters reels, so everything sent IS relevant — scores should reflect that
- Updated relevance badge colors in view.html: green >= 0.85, yellow >= 0.70, red below

### 3. Markdown rendering in view.html
- Created `_md_to_html()` function in `src/utils/plan_writer.py` — converts **bold**, *italic*, `code`, bullet lists, and line breaks
- Replaced `_html_esc()` with `_md_to_html()` for all content fields: task descriptions, summaries, insights, swipe phrases, detailed notes, deliverables, recommendations
- Kept `_html_esc()` for metadata fields (titles, priorities, tool names) where markdown isn't expected
- HTML is still safe — `_md_to_html` escapes HTML first, then applies markdown conversion
- Added 7 unit tests for the new function

### 4. Tests
- 52 tests passing (up from 45)
- New tests cover `_md_to_html`: bold, italic, code, bullet lists, XSS safety, empty input, line breaks

## Key Decisions
- **Kimi K2.5 remains production model** — frame resize should bring its token usage much closer to Gemini's
- **Relevance scoring shifted up** — most reels should now score 0.85-0.95 instead of the previous lower baseline

## Priority Next Steps

### 1. Deploy all changes to production
- Three improvements need deploying: frame resize, relevance calibration, markdown rendering
- `git push origin main && git push origin main:deploy`
- Manual rebuild on server (see memory/MEMORY.md for deploy process)

### 2. Build real execution handlers
- `_execute_auto_task` in `src/services/executor.py:54-89` is still stubs
- Priority: `sales_script` handler (PUT to /api/script/sections)

### 3. Fix Coolify auto-deploy
- Webhook secret not set in Coolify DB
- Manual deploy works but adds friction

### 4. Production has 11 plans in review
- `plans/_index.json` on production — none approved/executed yet

## Context Notes
- Venv is at `venv/` (not `.venv/`)
- Container on Coolify: `l0g48c8g4wsskc40co4kssc8-054648262157` at `root@76.13.29.110`
- Compose file: `/data/coolify/applications/l0g48c8g4wsskc40co4kssc8/docker-compose.yaml`
- Plans volume: `l0g48c8g4wsskc40co4kssc8_reelbot-plans` (persists across container recreates)
- Telegram bot token in .env has Windows line endings — always `tr -d '\r'` when extracting
- 52 tests passing locally
