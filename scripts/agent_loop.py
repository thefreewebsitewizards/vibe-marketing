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
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

BASE_URL = os.getenv("REELBOT_URL", "https://reelbot.leadneedleai.com")
API_KEY = os.getenv("REELBOT_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
CLAUDE_CMD = os.getenv("CLAUDE_CMD", "claude")
CLAUDE_TIMEOUT = int(os.getenv("CLAUDE_TIMEOUT", "300"))

HEADERS = {}
if API_KEY:
    HEADERS["X-API-Key"] = API_KEY

# Map routing targets to local repo paths on the VPS
REPO_PATHS = {
    "tfww": "/home/openclaw/projects/tfww-website",
    "aias": "/home/openclaw/projects/aias",
    "ddb": "/home/openclaw/projects/ddb",
    "reelbot": "/home/openclaw/projects/reelbot",
    "claude-upgrades": "/home/openclaw/projects/reelbot",
    "ghl-fix": "/home/openclaw/projects/aias",
    "n8n-automations": "/home/openclaw/projects/aias",
}


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def send_telegram(message: str) -> None:
    """Send a Telegram notification. Fails silently if not configured."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("  Telegram not configured, skipping notification")
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": int(TELEGRAM_CHAT_ID),
                "text": message,
                "parse_mode": "Markdown",
            },
            timeout=10.0,
        )
    except Exception as e:
        log(f"  Telegram notification failed: {e}")


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


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    """Run a git command in the given directory."""
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )


def execute_claude_code(
    task: dict, reel_id: str, task_index: int, routing_target: str,
) -> tuple[bool, str]:
    """Run Claude Code CLI on a task. Returns (success, notes)."""
    repo_path = REPO_PATHS.get(routing_target, "")
    if not repo_path:
        return False, f"[claude_code] Unknown routing target '{routing_target}'"

    if not Path(repo_path).is_dir():
        return False, f"[claude_code] Repo not found at {repo_path}"

    title = task.get("title", "Untitled")
    description = task.get("description", "")
    tool_data = task.get("tool_data", {})
    files_to_modify = tool_data.get("files_to_modify", [])
    change_description = tool_data.get("change_description", "")

    branch_name = f"reelbot/{reel_id}-task-{task_index}"

    # 1. Checkout main and pull latest
    checkout = _run_git(["checkout", "main"], cwd=repo_path)
    if checkout.returncode != 0:
        return False, f"[claude_code] git checkout main failed: {checkout.stderr.strip()}"

    pull = _run_git(["pull", "origin", "main"], cwd=repo_path)
    if pull.returncode != 0:
        return False, f"[claude_code] git pull failed: {pull.stderr.strip()}"

    # 2. Create feature branch
    branch = _run_git(["checkout", "-b", branch_name], cwd=repo_path)
    if branch.returncode != 0:
        # Branch may already exist -- try switching to it
        switch = _run_git(["checkout", branch_name], cwd=repo_path)
        if switch.returncode != 0:
            return False, f"[claude_code] Failed to create branch {branch_name}: {branch.stderr.strip()}"

    # 3. Build prompt
    files_str = ", ".join(files_to_modify) if files_to_modify else "Determine from task description"
    prompt = (
        "You are executing a task from a ReelBot plan.\n\n"
        f"Task: {title}\n"
        f"Description: {description}\n"
        f"Files to modify: {files_str}\n"
        f"Change description: {change_description}\n\n"
        "Make the changes, then commit with a descriptive message.\n"
        "Do NOT push or create PRs -- that will be handled externally."
    )

    # 4. Run Claude Code CLI
    log(f"    Running Claude Code in {repo_path} (timeout: {CLAUDE_TIMEOUT}s)")
    try:
        result = subprocess.run(
            [
                CLAUDE_CMD, "-p", prompt,
                "--cwd", repo_path,
                "--allowedTools", "Edit,Write,Read,Bash,Glob,Grep",
                "--max-turns", "15",
            ],
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        _run_git(["checkout", "main"], cwd=repo_path)
        return False, f"[claude_code] Claude Code timed out after {CLAUDE_TIMEOUT}s"

    claude_stdout = result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout
    claude_stderr = result.stderr[-500:] if len(result.stderr) > 500 else result.stderr

    if result.returncode != 0:
        log(f"    Claude Code failed (exit {result.returncode})")
        _run_git(["checkout", "main"], cwd=repo_path)
        return False, (
            f"[claude_code] Claude Code failed (exit {result.returncode})\n"
            f"stderr: {claude_stderr}\n"
            f"stdout (tail): {claude_stdout[-500:]}"
        )

    # 5. Check if any commits were made on the branch
    diff_check = _run_git(["log", "main..HEAD", "--oneline"], cwd=repo_path)
    if not diff_check.stdout.strip():
        log(f"    Claude Code ran but made no commits")
        _run_git(["checkout", "main"], cwd=repo_path)
        return False, "[claude_code] Claude Code ran successfully but made no commits"

    commit_count = len(diff_check.stdout.strip().splitlines())

    # 6. Push the branch
    push = _run_git(["push", "-u", "origin", branch_name], cwd=repo_path)
    if push.returncode != 0:
        log(f"    git push failed: {push.stderr.strip()}")
        _run_git(["checkout", "main"], cwd=repo_path)
        return False, f"[claude_code] git push failed: {push.stderr.strip()}"

    # 7. Create PR via gh CLI
    pr_title = f"[ReelBot] {title}"
    pr_body = (
        f"## Summary\n\n"
        f"{description}\n\n"
        f"## Source\n\n"
        f"Auto-generated from ReelBot plan `{reel_id}`, task {task_index}.\n\n"
        f"**Commits:** {commit_count}\n"
        f"**Routing target:** {routing_target}\n\n"
        f"---\n"
        f"*This PR was created automatically by the ReelBot agent loop.*"
    )

    try:
        pr_result = subprocess.run(
            [
                "gh", "pr", "create",
                "--title", pr_title,
                "--body", pr_body,
                "--head", branch_name,
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        pr_result = None

    pr_url = ""
    if pr_result and pr_result.returncode == 0:
        pr_url = pr_result.stdout.strip()
        log(f"    PR created: {pr_url}")
    else:
        err = pr_result.stderr.strip() if pr_result else "timeout"
        log(f"    PR creation failed: {err}")

    # 8. Go back to main
    _run_git(["checkout", "main"], cwd=repo_path)

    # 9. Build result notes
    notes = f"[claude_code] Executed successfully ({commit_count} commit(s))"
    if pr_url:
        notes += f" | PR: {pr_url}"

    # 10. Send Telegram notification
    if pr_url:
        send_telegram(
            f"*ReelBot Code Task Completed*\n\n"
            f"*{title}*\n"
            f"Branch: `{branch_name}`\n"
            f"PR: {pr_url}"
        )
    else:
        send_telegram(
            f"*ReelBot Code Task Completed*\n\n"
            f"*{title}*\n"
            f"Branch: `{branch_name}` pushed (PR creation failed)"
        )

    return True, notes


def handle_task(reel_id: str, task: dict, plan: dict) -> bool:
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
                notes_parts.append(f"[agent] Content task with {len(drafts)} draft(s) -- logged")
                handled = True
            else:
                notes_parts.append(f"[agent] No drafts for content task -- skipped")

        elif tool == "knowledge_base":
            # KB tasks are auto-executed by the server-side executor
            # If we see one pending here, it means the executor didn't run
            content = tool_data.get("content", task.get("description", ""))
            if content:
                notes_parts.append(f"[agent] KB note: {content[:80]}")
                handled = True
            else:
                notes_parts.append(f"[agent] KB task with no content -- skipped")

        elif tool == "claude_code":
            routing_target = plan.get("routed_to", "") or plan.get("category", "")
            # Allow tool_data to override routing target
            if tool_data.get("routing_target"):
                routing_target = tool_data["routing_target"]

            if not routing_target:
                notes_parts.append("[agent] claude_code task has no routing target -- skipped")
                continue

            success, result_notes = execute_claude_code(
                task, reel_id, index, routing_target,
            )
            notes_parts.append(result_notes)
            if success:
                handled = True
            else:
                # Mark failed immediately so it doesn't retry every poll
                mark_task(reel_id, index, "failed", result_notes)
                send_telegram(
                    f"*ReelBot Code Task Failed*\n\n"
                    f"*{title}*\n"
                    f"Target: `{routing_target}`\n"
                    f"Error: {result_notes[:200]}"
                )
                return False

        else:
            notes_parts.append(f"[agent] Unknown tool '{tool}' -- skipped")

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
            if handle_task(reel_id, task, plan):
                total_handled += 1

    log(f"Done -- handled {total_handled} task(s)")
    return total_handled


def main():
    parser = argparse.ArgumentParser(description="OpenClaw agent loop for ReelBot")
    parser.add_argument("--watch", nargs="?", const=60, type=int, metavar="SECONDS",
                        help="Poll continuously (default: every 60s)")
    args = parser.parse_args()

    log(f"Agent loop starting -- target: {BASE_URL}")

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
