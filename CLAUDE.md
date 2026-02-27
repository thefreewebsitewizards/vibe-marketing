# Vibe Marketing — Claude Code Instructions

## Business Context

This project belongs to **Lead Needle LLC / The Free Website Wizards**.
- AI-powered appointment setting and lead generation for local service businesses
- Services: website builds, AI chatbots, automated follow-up, paid ads management
- Target clients: HVAC, plumbers, roofers, dentists, lawyers, and other local service businesses
- Tech stack: GoHighLevel (CRM), n8n (automations at n8n.leadneedleai.com), Claude/AI, Meta ads

## What This Project Does

Instagram Reel → Business Strategy Pipeline:
1. Receives an Instagram Reel URL (via Telegram bot → n8n → FastAPI)
2. Downloads the video, extracts audio, transcribes it
3. Analyzes the transcript with Claude for actionable business insights
4. Generates an implementation plan with concrete tasks
5. Stores everything in `plans/` for autonomous execution

## Plan Lifecycle

Plans go through these statuses:
1. **review** — Just created. Sent to user via Telegram for review. DO NOT execute.
2. **approved** — User reviewed and approved. Ready for execution.
3. **in_progress** — Currently being executed.
4. **completed** — All tasks done.
5. **failed** — Something went wrong.

## Autonomous Execution

When activated, check `plans/_index.json` for plans with `"status": "approved"`.

**IMPORTANT:** Only execute plans with status `"approved"`. Plans with status `"review"` are waiting for the user to review them via Telegram — do not touch them.

For each approved plan:
1. Read the plan at `plans/{plan_dir}/plan.md`
2. Review each task's description, deliverables, and tools
3. Execute tasks you can handle (code, content, n8n workflows, GHL config)
4. Update the plan's `metadata.json` status as you work
5. Update `plans/_index.json` entry status to `"in_progress"` then `"completed"`

### Execution Rules
- **CAN DO:** Write code, create n8n workflow JSONs, draft content, create scripts, update configs
- **CAN DO:** Create GHL automation configs, draft email/SMS sequences, generate ad copy
- **ASK FIRST:** Anything that costs money (running ads, buying domains), sending messages to real people
- **NEVER:** Delete production data, modify .env secrets, push to main without review
- **NEVER:** Execute a plan that is still in `"review"` status

## Project Structure

```
src/main.py          — FastAPI app entry point
src/config.py        — Pydantic Settings (loads .env)
src/models.py        — All data models
src/routers/         — API endpoints (reel.py, health.py)
src/services/        — Pipeline stages (downloader, audio, transcriber, analyzer, planner)
src/prompts/         — Claude prompt templates
src/utils/           — Plan writing, file operations
plans/               — Generated plans and knowledge base
scripts/             — CLI tools and setup
n8n/                 — Workflow export JSONs
```

## Development Commands

```bash
# Setup
source .venv/bin/activate
pip install -e ".[dev]"

# Run API server
uvicorn src.main:app --reload --host 127.0.0.1 --port 8000

# Process a reel from CLI
python scripts/process_reel.py "https://instagram.com/reel/..."

# Run tests
pytest tests/

# Health check
curl http://localhost:8000/health
```

## Key Files

- `.env` — All secrets (NEVER commit, NEVER modify)
- `plans/_index.json` — Plan registry with status tracking
- `src/prompts/analyze_reel.py` — Analysis prompt (tune for better insights)
- `src/prompts/generate_plan.py` — Plan generation prompt (tune for better tasks)
