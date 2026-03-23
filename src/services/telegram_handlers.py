"""Telegram bot message and callback handlers.

Contains handler functions for commands, messages, and inline buttons.
Delegates similarity flow to telegram_similarity module.
"""
import asyncio
import re
import time
from pathlib import Path

# Track active pipelines for status messages
_active_count = 0

# Pause mode: queue URLs without processing
_paused = False
_paused_queue: list[dict] = []

from telegram import Update
from telegram.ext import ContextTypes
from loguru import logger

from src.config import settings
from src.models import (
    PipelineResult, PlanStatus, TranscriptResult, CostBreakdown,
)
from src.services.downloader import download_reel, extract_shortcode
from src.services.audio import extract_audio
from src.services.frames import extract_keyframes
from src.services.transcriber import transcribe
from src.services.analyzer import analyze_reel, analyze_carousel
from src.services.ocr import extract_text_from_images
from src.services.planner import generate_plan, check_plan_similarity
from src.utils.file_ops import create_temp_dir, cleanup_temp_dir
from src.utils.plan_writer import write_plan
from src.utils.plan_manager import (
    get_plans_by_status,
    find_plan_by_id,
    is_duplicate,
)
from src.services.telegram_similarity import (
    save_analysis_for_resume,
    send_similarity_notification,
    handle_generate_anyway,
    handle_skip_similar,
)

INSTAGRAM_PATTERN = re.compile(r"instagram\.com/(reel|reels|p)/")

# Track last processed reel per chat for quick approve
_last_reel: dict[int, str] = {}

# Message logs for debugging
_CHAT_LOG_JSONL = Path(settings.plans_dir) / "_chat_log.jsonl"
_CHAT_LOG_TXT = Path(settings.plans_dir) / "_telegramlogs.txt"


def _log_message(chat_id: int, text: str, direction: str = "in", sender: str = "") -> None:
    """Append a message to both chat logs (JSONL for API, txt for human reading)."""
    import json
    from datetime import datetime

    now = datetime.now()

    # JSONL log (for /chat-log API)
    try:
        entry = {"ts": now.isoformat(), "dir": direction, "chat": chat_id, "text": text[:500]}
        with open(_CHAT_LOG_JSONL, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass

    # Human-readable log (telegramlogs.txt)
    try:
        ts = now.strftime("%-m/%-d/%Y %-I:%M %p")
        name = sender or ("Dylan Spencer" if direction == "in" else "vibemarkting")
        # Collapse multi-line messages to keep log scannable
        short = text[:300].replace("\n", " | ") if len(text) > 300 else text.replace("\n", " | ")
        with open(_CHAT_LOG_TXT, "a") as f:
            f.write(f"[{ts}] {name}: {short}\n")
    except Exception:
        pass


def _esc(text: str) -> str:
    """Escape Telegram Markdown special characters in dynamic/LLM text."""
    if not text:
        return text
    for ch in ("*", "_", "`", "["):
        text = text.replace(ch, "\\" + ch)
    return text


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me an Instagram Reel link and I'll analyze it.\n\n"
        "Commands:\n"
        "/status -- Show execution summary\n"
        "/plans -- Show all plans\n"
        "/pause -- Queue reels without processing\n"
        "/resume -- Process all queued reels\n\n"
        "Review and approve plans at the web dashboard."
    )


async def handle_inline_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard button presses (similarity flow only)."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if ":" not in data:
        return

    parts = data.split(":")
    action = parts[0]
    reel_id = parts[1] if len(parts) > 1 else ""

    if action == "generate_anyway":
        await handle_generate_anyway(reel_id, query)
    elif action == "skip_similar":
        await handle_skip_similar(reel_id, query)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show execution status of all plans."""
    from src.services.executor import get_execution_summary

    summary = get_execution_summary()
    await update.message.reply_text(f"```\n{summary}\n```", parse_mode="Markdown")


async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all plans grouped by status."""
    lines = ["*Plans Overview*\n"]

    for status in [PlanStatus.PROCESSING, PlanStatus.REVIEW, PlanStatus.APPROVED,
                   PlanStatus.IN_PROGRESS, PlanStatus.COMPLETED, PlanStatus.SKIPPED,
                   PlanStatus.FAILED]:
        plans = get_plans_by_status(status)
        if plans:
            emoji = {
                "processing": "...", "review": ">>", "approved": "OK",
                "in_progress": ">>", "completed": "OK", "skipped": ">>", "failed": "XX",
            }
            lines.append(f"\n{emoji.get(status.value, '.')} *{status.value.upper()}* ({len(plans)})")
            for p in plans[-5:]:
                theme_hint = f" | {p.get('theme', '')[:40]}" if p.get("theme") else ""
                lines.append(f"  `{p['reel_id']}` -- {p['title'][:50]}{theme_hint}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pause processing — reels get queued but not processed."""
    global _paused
    _paused = True
    await update.message.reply_text(
        f"Paused. Send reels and they'll be queued.\n"
        f"Use /resume to process the queue ({len(_paused_queue)} queued so far)."
    )


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resume processing and drain the queued reels."""
    global _paused
    _paused = False
    queue = list(_paused_queue)
    _paused_queue.clear()

    if not queue:
        await update.message.reply_text("Resumed. No queued reels to process.")
        return

    await update.message.reply_text(f"Resumed. Processing {len(queue)} queued reel(s)...")
    for item in queue:
        asyncio.create_task(
            _process_queued_reel(update, item["reel_id"], item["url"], item["user_context"], item["chat_id"])
        )


async def _process_queued_reel(update, reel_id, url, user_context, chat_id):
    """Process a reel from the paused queue."""
    await _process_reel_locked(update, reel_id, url, user_context, chat_id)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    chat_id = update.message.chat.id

    # Log all incoming messages to file for debugging
    _log_message(chat_id, text)

    if not INSTAGRAM_PATTERN.search(text):
        await update.message.reply_text(
            "Send me an Instagram Reel URL, or use /plans to see status."
        )
        return

    # Extract all Instagram URLs from the message
    urls = re.findall(r"https?://[^\s]+instagram\.com/[^\s]+", text)
    if not urls:
        urls = [text]

    # Strip URLs from text to get user context
    user_context = text
    for u in urls:
        user_context = user_context.replace(u, "")
    user_context = user_context.strip()

    # Collect valid reels, skip duplicates
    reels = []
    for url in urls:
        try:
            reel_id = extract_shortcode(url)
        except ValueError:
            continue

        if is_duplicate(reel_id):
            entry = find_plan_by_id(reel_id)
            base_url = settings.public_url or f"http://{settings.host}:{settings.port}"
            view_url = f"{base_url}/plans/{reel_id}/view"
            status = entry["status"] if entry else "unknown"
            msg = f"Already processed ({status}): {view_url}"
            await update.message.reply_text(msg)
            _log_message(chat_id, msg, direction="out")
            continue

        if _paused:
            _paused_queue.append({"reel_id": reel_id, "url": url, "user_context": user_context, "chat_id": chat_id})
            await update.message.reply_text(f"Queued: {reel_id} ({len(_paused_queue)} in queue)")
            continue

        reels.append((reel_id, url))

    if not reels:
        return

    # Acknowledge and launch all pipelines concurrently
    if len(reels) == 1:
        reel_id, url = reels[0]
        active = _active_count
        if active > 0:
            ack = f"Got it ({reel_id}) — {active} reel(s) active, adding yours."
        else:
            ack = f"Got it ({reel_id}) — processing now..."
        await update.message.reply_text(ack)
        _log_message(chat_id, ack, direction="out")
        asyncio.create_task(_process_reel_locked(update, reel_id, url, user_context, chat_id))
    else:
        ids = ", ".join(r[0] for r in reels)
        ack = f"Got {len(reels)} reels ({ids}) — processing all in parallel..."
        await update.message.reply_text(ack)
        _log_message(chat_id, ack, direction="out")
        for reel_id, url in reels:
            asyncio.create_task(_process_reel_locked(update, reel_id, url, user_context, chat_id))


async def _process_reel_locked(update, reel_id, url, user_context, chat_id):
    """Process a reel while holding the processing lock."""
    global _active_count
    _active_count += 1
    try:
        await _process_reel_inner(update, reel_id, url, user_context, chat_id)
    finally:
        _active_count -= 1


async def _process_reel_inner(update, reel_id, url, user_context, chat_id):
    """Inner pipeline logic, called from _process_reel_locked."""
    from src.utils.processing_stats import get_estimate, record_time

    t0 = time.monotonic()
    estimate = get_estimate()
    total_steps = 4
    progress_msg = await update.message.reply_text(
        f"Processing reel... ~{estimate}s estimated"
    )

    async def _progress(step: int, label: str):
        elapsed = int(time.monotonic() - t0)
        remaining = max(0, estimate - elapsed)
        time_str = f"~{remaining}s left" if remaining > 5 else f"{elapsed}s"
        try:
            await progress_msg.edit_text(
                f"{label} (step {step}/{total_steps}, {time_str})"
            )
        except Exception:
            pass

    try:
        pipeline_out = await _run_telegram_pipeline(
            reel_id, url, user_context, _progress,
        )
        if pipeline_out is None:
            # Similarity flow handled it -- should not happen, indicates a bug
            return
        if isinstance(pipeline_out, tuple):
            # Similarity detected: (analysis, similarity, costs)
            analysis, similarity, costs = pipeline_out
            await send_similarity_notification(update, reel_id, analysis, similarity, costs)
            return

        result = pipeline_out
        write_plan(result)
        cleanup_temp_dir(reel_id)

        _last_reel[chat_id] = reel_id

        elapsed = int(time.monotonic() - t0)
        record_time(elapsed)

        base_url = settings.public_url or f"http://{settings.host}:{settings.port}"
        view_url = f"{base_url}/plans/{reel_id}/view"
        action_line = result.plan.recommended_action or result.plan.summary or result.plan.theme or "Review the plan for details"
        notification = (
            f"*{_esc(result.plan.title)}*\n"
            f"{_esc(action_line)}\n\n"
            f"{view_url}"
        )

        try:
            await progress_msg.delete()
        except Exception:
            pass

        try:
            await update.message.reply_text(notification, parse_mode="Markdown")
        except Exception:
            # Markdown parsing failed — send plain text fallback
            plain = f"{result.plan.title}\n{action_line}\n\n{view_url}"
            await update.message.reply_text(plain)
        _log_message(chat_id, notification, direction="out")
        logger.info(f"Telegram: sent notification for {reel_id} in {elapsed}s")

    except Exception as e:
        elapsed = int(time.monotonic() - t0)
        logger.error(f"Telegram pipeline failed after {elapsed}s: {e}", exc_info=True)
        # Don't leak internal error details to user
        error_type = type(e).__name__
        error_msg = f"Failed to process reel ({elapsed}s). Error type: {error_type}. Check server logs."
        await update.message.reply_text(error_msg)
        _log_message(chat_id, error_msg, direction="out")


async def _run_telegram_pipeline(
    reel_id: str,
    url: str,
    user_context: str,
    progress_cb,
) -> PipelineResult | tuple:
    """Run the download-transcribe-analyze-plan pipeline.

    Returns PipelineResult on success, or a (analysis, similarity, costs)
    tuple if similarity was detected and the caller should notify.
    """
    temp_dir = create_temp_dir(reel_id)
    costs = CostBreakdown()

    download_result, metadata = await asyncio.to_thread(download_reel, url, temp_dir)

    if metadata.content_type == "carousel":
        await progress_cb(2, "Reading carousel images...")
        image_paths = download_result
        ocr_text = await asyncio.to_thread(extract_text_from_images, image_paths)
        transcript = TranscriptResult(text=ocr_text, language="en")
        await progress_cb(3, "Analyzing content...")
        analysis, analysis_cr = await asyncio.to_thread(
            analyze_carousel, ocr_text, metadata, image_paths, user_context,
        )
    else:
        await progress_cb(2, "Transcribing...")
        video_path = download_result
        audio_path = await asyncio.to_thread(extract_audio, video_path, temp_dir)
        frame_paths = await asyncio.to_thread(extract_keyframes, video_path, temp_dir)
        from src.services.transcriber import whisper_semaphore
        async with whisper_semaphore:
            transcript = await asyncio.to_thread(transcribe, audio_path)
        await progress_cb(3, "Analyzing content...")
        analysis, analysis_cr = await asyncio.to_thread(
            analyze_reel, transcript, metadata, frame_paths, user_context,
        )
    costs.add(
        "analysis", analysis_cr.model, analysis_cr.prompt_tokens,
        analysis_cr.completion_tokens, analysis_cr.cost_usd, analysis_cr.generation_id,
    )

    await progress_cb(3, "Checking similarity...")
    similarity, sim_cr = await asyncio.to_thread(check_plan_similarity, analysis)
    if sim_cr:
        costs.add(
            "similarity", sim_cr.model, sim_cr.prompt_tokens,
            sim_cr.completion_tokens, sim_cr.cost_usd, sim_cr.generation_id,
        )

    if similarity.recommendation == "skip":
        save_analysis_for_resume(reel_id, analysis, metadata, similarity, costs, transcript)
        cleanup_temp_dir(reel_id)
        return (analysis, similarity, costs)

    await progress_cb(4, "Generating plan...")
    plan, plan_cr = await asyncio.to_thread(
        generate_plan, analysis, metadata, user_context, similarity,
    )
    costs.add(
        "plan", plan_cr.model, plan_cr.prompt_tokens,
        plan_cr.completion_tokens, plan_cr.cost_usd, plan_cr.generation_id,
    )
    costs.resolve_actual_costs()

    return PipelineResult(
        reel_id=reel_id, status=PlanStatus.REVIEW, metadata=metadata,
        transcript=transcript, analysis=analysis, plan=plan,
        similarity=similarity, cost_breakdown=costs,
    )
