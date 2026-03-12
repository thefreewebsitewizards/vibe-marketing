#!/usr/bin/env python3
"""OpenClaw Agent Loop — polls ReelBot for approved plans and executes tasks.

Usage:
    python scripts/agent_loop.py              # Single pass
    python scripts/agent_loop.py --watch      # Poll every 60s
    python scripts/agent_loop.py --watch 30   # Poll every 30s
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

BASE_URL = os.getenv("REELBOT_URL", "https://reelbot.leadneedleai.com")
API_KEY = os.getenv("REELBOT_API_KEY", "")

HEADERS = {}
if API_KEY:
    HEADERS["X-API-Key"] = API_KEY


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def get_approved_plans() -> list[dict]:
    resp = httpx.get(f"{BASE_URL}/plans/approved", headers=HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_tasks(reel_id: str) -> dict:
    resp = httpx.get(f"{BASE_URL}/plans/{reel_id}/tasks", headers=HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()


def mark_task(reel_id: str, task_index: int, status: str, notes: str) -> None:
    resp = httpx.patch(
        f"{BASE_URL}/plans/{reel_id}/tasks/{task_index}",
        headers={**HEADERS, "Content-Type": "application/json"},
        json={"status": status, "notes": notes},
        timeout=10,
    )
    resp.raise_for_status()
    log(f"  Marked task {task_index} as {status}")


def handle_task(reel_id: str, task: dict) -> bool:
    """Attempt to handle a task. Returns True if handled."""
    index = task["index"]
    title = task["title"]
    tools = task.get("tools", [])
    tool_data = task.get("tool_data", {})

    # Skip already-done or human tasks
    if task["status"] != "pending":
        return False

    log(f"  Task {index}: {title} (tools: {tools})")

    notes_parts = []
    handled = False

    for tool in tools:
        if tool == "sales_script" and tool_data.get("new_content"):
            section_id = tool_data.get("section_id", "")
            if section_id:
                try:
                    resp = httpx.put(
                        f"{BASE_URL}/api/script/sections/{section_id}",
                        headers={**HEADERS, "Content-Type": "application/json"},
                        json={"content": tool_data["new_content"]},
                        timeout=10,
                    )
                    resp.raise_for_status()
                    notes_parts.append(f"[agent] Updated script section '{section_id}'")
                    handled = True
                except Exception as e:
                    notes_parts.append(f"[agent] Failed to update section '{section_id}': {e}")

        elif tool in ("content", "meta_ads", "email", "social_media"):
            drafts = tool_data.get("drafts", task.get("deliverables", []))
            if drafts:
                notes_parts.append(f"[agent] Content task with {len(drafts)} draft(s) — logged")
                handled = True
            else:
                notes_parts.append(f"[agent] No drafts for content task — skipped")

        elif tool == "knowledge_base":
            # KB tasks are auto-executed by the server-side executor
            # If we see one pending here, it means the executor didn't run
            content = tool_data.get("content", task.get("description", ""))
            if content:
                notes_parts.append(f"[agent] KB note: {content[:80]}")
                handled = True
            else:
                notes_parts.append(f"[agent] KB task with no content — skipped")

        elif tool == "n8n":
            notes_parts.append(f"[agent] n8n workflow spec — logged for manual import")
            handled = True

        elif tool == "claude_code":
            notes_parts.append(f"[agent] Code task — requires Claude Code session")
            # Don't mark as handled — this needs a real Claude Code session

        else:
            notes_parts.append(f"[agent] Unknown tool '{tool}' — skipped")

    if handled:
        mark_task(reel_id, index, "completed", "; ".join(notes_parts))
    elif notes_parts:
        log(f"    Skipped: {'; '.join(notes_parts)}")

    return handled


def run_once() -> int:
    """Single pass over approved plans. Returns count of tasks handled."""
    plans = get_approved_plans()
    if not plans:
        log("No approved plans found")
        return 0

    log(f"Found {len(plans)} approved plan(s)")
    total_handled = 0

    for plan in plans:
        reel_id = plan["reel_id"]
        log(f"Plan: {plan.get('title', reel_id)}")

        tasks_data = get_tasks(reel_id)
        tasks = tasks_data.get("tasks", [])
        pending = [t for t in tasks if t["status"] == "pending"]

        if not pending:
            log(f"  No pending tasks")
            continue

        for task in pending:
            if handle_task(reel_id, task):
                total_handled += 1

    log(f"Done — handled {total_handled} task(s)")
    return total_handled


def main():
    parser = argparse.ArgumentParser(description="OpenClaw agent loop for ReelBot")
    parser.add_argument("--watch", nargs="?", const=60, type=int, metavar="SECONDS",
                        help="Poll continuously (default: every 60s)")
    args = parser.parse_args()

    log(f"Agent loop starting — target: {BASE_URL}")

    if args.watch:
        log(f"Watch mode: polling every {args.watch}s (Ctrl+C to stop)")
        while True:
            try:
                run_once()
            except httpx.HTTPError as e:
                log(f"HTTP error: {e}")
            except Exception as e:
                log(f"Error: {e}")
            time.sleep(args.watch)
    else:
        try:
            run_once()
        except httpx.HTTPError as e:
            log(f"HTTP error: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
