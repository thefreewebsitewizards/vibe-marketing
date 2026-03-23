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

# Map routing targets and categories to local repo paths on the VPS
REPO_PATHS = {
    "tfww": "/home/openclaw/projects/tfww-website",
    "aias": "/home/openclaw/projects/aias",
    "ddb": "/home/openclaw/projects/ddb",
    "reelbot": "/home/openclaw/projects/reelbot",
    "claude-upgrades": "/home/openclaw/projects/reelbot",
    "ghl-fix": "/home/openclaw/projects/aias",
    "n8n-automations": "/home/openclaw/projects/aias",
    # Category fallbacks (analysis categories that aren't routing targets)
    "ai_automation": "/home/openclaw/projects/aias",
    "sales": "/home/openclaw/projects/tfww-website",
    "marketing": "/home/openclaw/projects/tfww-website",
    "social_media": "/home/openclaw/projects/ddb",
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


def get_actionable_plans() -> list[dict]:
    """Get plans that may have pending tasks (approved or in_progress)."""
    resp = httpx.get(f"{BASE_URL}/plans/", headers=HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    plans = []
    for status in ("approved", "in_progress"):
        plans.extend(data.get(status, []))
    return plans


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


MAX_RETRIES = 2  # try once, retry once on test failure

# Test commands per repo (run from repo root)
TEST_COMMANDS = {
    "reelbot": ["python3", "-m", "pytest", "tests/", "-q", "--tb=short"],
    "aias": ["npm", "test", "--", "--silent"],
    "tfww-website": None,  # no test suite
    "ddb": ["python3", "-m", "pytest", "tests/", "-q", "--tb=short"],
}


def _detect_test_cmd(repo_path: str) -> list[str] | None:
    """Detect test command from repo name."""
    repo_name = Path(repo_path).name
    return TEST_COMMANDS.get(repo_name)


def _run_tests(repo_path: str) -> tuple[bool, str]:
    """Run the test suite for a repo. Returns (passed, output)."""
    test_cmd = _detect_test_cmd(repo_path)
    if not test_cmd:
        log(f"    No test suite for {Path(repo_path).name} -- skipping validation")
        return True, "no test suite"

    log(f"    Running tests: {' '.join(test_cmd)}")
    try:
        result = subprocess.run(
            test_cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False, "tests timed out after 120s"

    output = result.stdout[-1000:] if len(result.stdout) > 1000 else result.stdout
    if result.returncode == 0:
        log(f"    Tests passed")
        return True, output
    else:
        log(f"    Tests failed (exit {result.returncode})")
        stderr = result.stderr[-500:] if len(result.stderr) > 500 else result.stderr
        return False, f"{output}\n{stderr}"


def execute_claude_code(
    task: dict, reel_id: str, task_index: int, routing_target: str,
) -> tuple[bool, str]:
    """Run Claude Code CLI on a task with test validation and auto-merge.

    Flow: make changes -> run tests -> pass = merge to main, fail = retry once.
    Returns (success, notes).
    """
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

    # Pull latest main
    _run_git(["checkout", "main"], cwd=repo_path)
    pull = _run_git(["pull", "origin", "main"], cwd=repo_path)
    if pull.returncode != 0:
        return False, f"[claude_code] git pull failed: {pull.stderr.strip()}"

    files_str = ", ".join(files_to_modify) if files_to_modify else "Determine from task description"
    base_prompt = (
        "You are executing a task from a ReelBot plan.\n\n"
        f"Task: {title}\n"
        f"Description: {description}\n"
        f"Files to modify: {files_str}\n"
        f"Change description: {change_description}\n\n"
        "Make the changes, then commit with a descriptive message.\n"
        "Do NOT push or create PRs -- that will be handled externally."
    )

    test_output = ""  # Initialize for retry prompt context
    for attempt in range(1, MAX_RETRIES + 1):
        log(f"    Attempt {attempt}/{MAX_RETRIES}")

        # Create a fresh branch for each attempt
        branch_name = f"reelbot/{reel_id}-task-{task_index}"
        if attempt > 1:
            branch_name += f"-retry{attempt}"

        # Reset to main before each attempt
        _run_git(["checkout", "main"], cwd=repo_path)
        _run_git(["branch", "-D", branch_name], cwd=repo_path)  # clean up if exists
        _run_git(["checkout", "-b", branch_name], cwd=repo_path)

        # Build prompt (include test failure context on retry)
        prompt = base_prompt
        if attempt > 1:
            prompt += (
                f"\n\nIMPORTANT: Previous attempt failed tests. Here is the test output:\n"
                f"```\n{test_output[-1500:]}\n```\n"
                f"Fix the issues and make the tests pass."
            )

        # Run Claude Code
        log(f"    Running Claude Code in {repo_path} (timeout: {CLAUDE_TIMEOUT}s)")
        try:
            result = subprocess.run(
                [
                    CLAUDE_CMD, "-p", prompt,
                    "--allowedTools", "Edit,Write,Read,Bash,Glob,Grep",
                    "--max-turns", "15",
                ],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=CLAUDE_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            _run_git(["checkout", "main"], cwd=repo_path)
            if attempt == MAX_RETRIES:
                return False, f"[claude_code] Timed out after {CLAUDE_TIMEOUT}s (attempt {attempt})"
            continue

        if result.returncode != 0:
            stderr = result.stderr[-500:] if len(result.stderr) > 500 else result.stderr
            log(f"    Claude Code failed (exit {result.returncode}): {stderr.strip()}")
            _run_git(["checkout", "main"], cwd=repo_path)
            if attempt == MAX_RETRIES:
                return False, f"[claude_code] Failed (exit {result.returncode}): {stderr}"
            test_output = f"Claude Code error: {stderr}"
            continue

        # Check for commits
        diff_check = _run_git(["log", "main..HEAD", "--oneline"], cwd=repo_path)
        if not diff_check.stdout.strip():
            _run_git(["checkout", "main"], cwd=repo_path)
            if attempt == MAX_RETRIES:
                return False, "[claude_code] No commits made"
            continue

        commit_count = len(diff_check.stdout.strip().splitlines())

        # Run tests
        tests_passed, test_output = _run_tests(repo_path)

        if tests_passed:
            # Merge to main
            _run_git(["checkout", "main"], cwd=repo_path)
            merge = _run_git(["merge", "--ff-only", branch_name], cwd=repo_path)
            if merge.returncode != 0:
                # ff-only failed, try regular merge
                merge = _run_git(["merge", branch_name, "-m", f"Merge {branch_name}"], cwd=repo_path)

            if merge.returncode != 0:
                return False, f"[claude_code] Merge failed: {merge.stderr.strip()}"

            # Push main
            push = _run_git(["push", "origin", "main"], cwd=repo_path)
            if push.returncode != 0:
                return False, f"[claude_code] Push failed: {push.stderr.strip()}"

            # Clean up branch
            _run_git(["branch", "-d", branch_name], cwd=repo_path)

            notes = f"[claude_code] Done -- {commit_count} commit(s) merged to main"
            send_telegram(
                f"*ReelBot Task Auto-Merged*\n\n"
                f"*{title}*\n"
                f"Repo: `{Path(repo_path).name}`\n"
                f"Commits: {commit_count}\n"
                f"Tests: passed"
            )
            return True, notes

        else:
            # Tests failed
            log(f"    Tests failed on attempt {attempt}")
            if attempt == MAX_RETRIES:
                # Final attempt failed -- leave branch for debugging, don't merge
                _run_git(["checkout", "main"], cwd=repo_path)
                notes = (
                    f"[claude_code] Tests failed after {MAX_RETRIES} attempts\n"
                    f"Branch: {branch_name}\n"
                    f"Test output: {test_output[-500:]}"
                )
                send_telegram(
                    f"*ReelBot Task Failed Tests*\n\n"
                    f"*{title}*\n"
                    f"Repo: `{Path(repo_path).name}`\n"
                    f"Attempts: {MAX_RETRIES}\n"
                    f"Branch `{branch_name}` left for debugging"
                )
                return False, notes
            # Reset for retry -- test_output will be fed into next prompt
            _run_git(["checkout", "main"], cwd=repo_path)

    return False, "[claude_code] Unexpected exit from retry loop"


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
            # Determine target repo: tool_data override > infer from description > plan route
            routing_target = tool_data.get("routing_target", "")
            if not routing_target:
                # Infer from task description/title — look for project names
                task_text = (title + " " + task.get("description", "")).lower()
                if "aias" in task_text:
                    routing_target = "aias"
                elif "tfww" in task_text or "website" in task_text:
                    routing_target = "tfww"
                elif "ddb" in task_text or "dylan does" in task_text:
                    routing_target = "ddb"
                elif "reelbot" in task_text:
                    routing_target = "reelbot"
                else:
                    routing_target = plan.get("routed_to", "") or plan.get("category", "")

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
    plans = get_actionable_plans()
    if not plans:
        log("No actionable plans found")
        return 0

    log(f"Found {len(plans)} actionable plan(s)")
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
