import asyncio
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from loguru import logger

from src.config import settings
from src.models import (
    AnalysisResult, PipelineResult, PlanStatus, ReelMetadata,
    SimilarityResult, TranscriptResult, CostBreakdown,
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
    get_index,
    save_index,
)
INSTAGRAM_PATTERN = re.compile(r"instagram\.com/(reel|reels|p)/")

# Track last processed reel per chat for quick approve
_last_reel: dict[int, str] = {}


def _esc(text: str) -> str:
    """Escape Telegram Markdown special characters in dynamic/LLM text."""
    if not text:
        return text
    # Telegram Markdown v1 special chars: * _ ` [
    for ch in ("*", "_", "`", "["):
        text = text.replace(ch, "\\" + ch)
    return text


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me an Instagram Reel link and I'll analyze it.\n\n"
        "Commands:\n"
        "/status — Show execution summary\n"
        "/plans — Show all plans\n\n"
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
        await _handle_generate_anyway(reel_id, query)
    elif action == "skip_similar":
        await _handle_skip_similar(reel_id, query)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show execution status of all plans."""
    from src.services.executor import get_execution_summary

    summary = get_execution_summary()
    await update.message.reply_text(f"```\n{summary}\n```", parse_mode="Markdown")


async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all plans grouped by status."""
    lines = ["*Plans Overview*\n"]

    for status in [PlanStatus.PROCESSING, PlanStatus.REVIEW, PlanStatus.APPROVED, PlanStatus.IN_PROGRESS, PlanStatus.COMPLETED, PlanStatus.SKIPPED, PlanStatus.FAILED]:
        plans = get_plans_by_status(status)
        if plans:
            emoji = {"processing": "⏳", "review": "📋", "approved": "✅", "in_progress": "⚡", "completed": "✔️", "skipped": "⏭️", "failed": "❌"}
            lines.append(f"\n{emoji.get(status.value, '•')} *{status.value.upper()}* ({len(plans)})")
            for p in plans[-5:]:  # Show last 5 per status
                theme_hint = f" | {p.get('theme', '')[:40]}" if p.get("theme") else ""
                lines.append(f"  `{p['reel_id']}` — {p['title'][:50]}{theme_hint}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    chat_id = update.message.chat.id

    if not INSTAGRAM_PATTERN.search(text):
        await update.message.reply_text(
            "Send me an Instagram Reel URL, or use /plans to see status."
        )
        return

    url_match = re.search(r"https?://[^\s]+instagram\.com/[^\s]+", text)
    url = url_match.group(0) if url_match else text

    # Extract user context (everything besides the URL)
    user_context = text.replace(url, "").strip() if url_match else ""

    # Duplicate detection
    try:
        reel_id = extract_shortcode(url)
    except ValueError as e:
        await update.message.reply_text(f"Invalid URL: {e}")
        return

    if is_duplicate(reel_id):
        entry = find_plan_by_id(reel_id)
        base_url = settings.public_url or f"http://{settings.host}:{settings.port}"
        view_url = f"{base_url}/plans/{reel_id}/view"
        status = entry["status"] if entry else "unknown"
        await update.message.reply_text(
            f"Already processed ({status}): {view_url}",
        )
        return

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
        temp_dir = create_temp_dir(reel_id)
        costs = CostBreakdown()

        download_result, metadata = await asyncio.to_thread(download_reel, url, temp_dir)

        if metadata.content_type == "carousel":
            await _progress(2, "Reading carousel images...")
            image_paths = download_result
            ocr_text = await asyncio.to_thread(extract_text_from_images, image_paths)
            transcript = TranscriptResult(text=ocr_text, language="en")
            await _progress(3, "Analyzing content...")
            analysis, analysis_cr = await asyncio.to_thread(analyze_carousel, ocr_text, metadata, image_paths, user_context)
        else:
            await _progress(2, "Transcribing...")
            video_path = download_result
            audio_path = await asyncio.to_thread(extract_audio, video_path, temp_dir)
            frame_paths = await asyncio.to_thread(extract_keyframes, video_path, temp_dir)
            transcript = await asyncio.to_thread(transcribe, audio_path)
            await _progress(3, "Analyzing content...")
            analysis, analysis_cr = await asyncio.to_thread(analyze_reel, transcript, metadata, frame_paths, user_context)
        costs.add("analysis", analysis_cr.model, analysis_cr.prompt_tokens, analysis_cr.completion_tokens, analysis_cr.cost_usd, analysis_cr.generation_id)

        await _progress(3, "Checking similarity...")
        similarity, sim_cr = await asyncio.to_thread(check_plan_similarity, analysis)
        if sim_cr:
            costs.add("similarity", sim_cr.model, sim_cr.prompt_tokens, sim_cr.completion_tokens, sim_cr.cost_usd, sim_cr.generation_id)

        if similarity.recommendation == "skip" or similarity.max_score > 70:
            _save_analysis_for_resume_telegram(reel_id, analysis, metadata, similarity, costs, transcript)
            await _send_similarity_notification(update, reel_id, analysis, similarity, costs)
            cleanup_temp_dir(reel_id)
            return

        await _progress(4, "Generating plan...")
        plan, plan_cr = await asyncio.to_thread(generate_plan, analysis, metadata, user_context)
        costs.add("plan", plan_cr.model, plan_cr.prompt_tokens, plan_cr.completion_tokens, plan_cr.cost_usd, plan_cr.generation_id)

        costs.resolve_actual_costs()

        result = PipelineResult(
            reel_id=reel_id,
            status=PlanStatus.REVIEW,
            metadata=metadata,
            transcript=transcript,
            analysis=analysis,
            plan=plan,
            similarity=similarity,
            cost_breakdown=costs,
        )
        write_plan(result)
        cleanup_temp_dir(reel_id)

        _last_reel[chat_id] = reel_id

        # Build compact notification
        elapsed = int(time.monotonic() - t0)
        record_time(elapsed)

        base_url = settings.public_url or f"http://{settings.host}:{settings.port}"
        view_url = f"{base_url}/plans/{reel_id}/view"

        action_line = plan.recommended_action or plan.summary
        notification = (
            f"*{_esc(plan.title)}*\n"
            f"{_esc(action_line)}\n\n"
            f"{view_url}"
        )

        try:
            await progress_msg.delete()
        except Exception:
            pass

        await update.message.reply_text(notification, parse_mode="Markdown")

        logger.info(f"Telegram: sent notification for {reel_id} in {elapsed}s")

    except Exception as e:
        elapsed = int(time.monotonic() - t0)
        logger.error(f"Telegram pipeline failed after {elapsed}s: {e}")
        await update.message.reply_text(f"Failed to process reel ({elapsed}s): {e}")


def _save_analysis_for_resume_telegram(
    reel_id: str,
    analysis: AnalysisResult,
    metadata: ReelMetadata,
    similarity: SimilarityResult,
    costs: CostBreakdown,
    transcript: TranscriptResult,
) -> str:
    """Save analysis artifacts so the pipeline can resume from plan generation."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    plan_dir_name = f"{date_str}_{reel_id}"
    plan_dir = settings.plans_dir / plan_dir_name
    plan_dir.mkdir(parents=True, exist_ok=True)

    (plan_dir / "analysis.json").write_text(
        json.dumps(analysis.model_dump(), indent=2)
    )
    (plan_dir / "metadata.json").write_text(json.dumps({
        "reel_id": reel_id,
        "source_url": metadata.url,
        "creator": metadata.creator,
        "shortcode": metadata.shortcode,
        "caption": metadata.caption,
        "duration": metadata.duration,
        "content_type": metadata.content_type,
        "status": PlanStatus.SKIPPED.value,
        "created_at": datetime.now().isoformat(),
        "cost_breakdown": costs.model_dump() if costs else None,
    }, indent=2))
    (plan_dir / "similarity.json").write_text(
        json.dumps(similarity.model_dump(), indent=2)
    )
    (plan_dir / "transcript.txt").write_text(transcript.text)

    logger.info(f"Saved analysis for resume at {plan_dir}")
    return plan_dir_name


async def _send_similarity_notification(
    update: Update,
    reel_id: str,
    analysis: AnalysisResult,
    similarity: SimilarityResult,
    costs: CostBreakdown,
) -> None:
    """Send a Telegram message about detected similarity with action buttons."""
    similar_lines = []
    for sp in similarity.similar_plans:
        overlap = ", ".join(sp.overlap_areas) if sp.overlap_areas else "general"
        similar_lines.append(
            f"  - {_esc(sp.title)} ({sp.score}% match, overlap: {_esc(overlap)})"
        )
    similar_text = "\n".join(similar_lines)

    theme_text = f"*Theme:* {_esc(analysis.theme)}\n" if analysis.theme else ""

    costs.resolve_actual_costs()
    cost_line = ""
    if costs.calls:
        actual = costs.total_actual_cost_usd
        if actual is not None:
            cost_line = f"\n\nAnalysis cost so far: ${actual:.4f} actual (${costs.total_cost_usd:.4f} est\\.)"
        else:
            cost_line = f"\n\nAnalysis cost so far: ${costs.total_cost_usd:.4f} est\\."

    message = (
        f"*Similar content detected*\n\n"
        f"{theme_text}"
        f"*Summary:* {_esc(analysis.summary[:200])}\n\n"
        f"*Similar to:*\n{similar_text}\n\n"
        f"Recommendation: {_esc(similarity.recommendation)}"
        f"{cost_line}"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Generate Anyway", callback_data=f"generate_anyway:{reel_id}",
            ),
            InlineKeyboardButton(
                "Skip", callback_data=f"skip_similar:{reel_id}",
            ),
        ]
    ])

    await update.message.reply_text(
        message, parse_mode="Markdown", reply_markup=keyboard,
    )


async def _handle_generate_anyway(reel_id: str, query) -> None:
    """Resume the pipeline from plan generation using saved analysis."""
    await query.edit_message_text("Generating plan from saved analysis...")

    try:
        plan_dir = _find_saved_analysis_dir(reel_id)
        if not plan_dir:
            await query.message.reply_text(f"Saved analysis not found for {reel_id}")
            return

        analysis_path = plan_dir / "analysis.json"
        metadata_path = plan_dir / "metadata.json"
        transcript_path = plan_dir / "transcript.txt"

        with open(analysis_path) as f:
            analysis = AnalysisResult(**json.load(f))

        with open(metadata_path) as f:
            meta_data = json.load(f)
        metadata = ReelMetadata(
            url=meta_data.get("source_url", ""),
            shortcode=meta_data.get("shortcode", reel_id),
            creator=meta_data.get("creator", ""),
            caption=meta_data.get("caption", ""),
            duration=meta_data.get("duration", 0.0),
            content_type=meta_data.get("content_type", "reel"),
        )

        transcript_text = ""
        if transcript_path.exists():
            transcript_text = transcript_path.read_text()
        transcript = TranscriptResult(text=transcript_text, language="en")

        # Load existing costs if available
        costs = CostBreakdown()
        if meta_data.get("cost_breakdown"):
            for call in meta_data["cost_breakdown"].get("calls", []):
                costs.add(
                    call["step"], call.get("model", ""),
                    call.get("prompt_tokens", 0),
                    call.get("completion_tokens", 0),
                    call.get("cost_usd", 0.0),
                )

        # Load similarity result
        similarity = None
        similarity_path = plan_dir / "similarity.json"
        if similarity_path.exists():
            with open(similarity_path) as f:
                similarity = SimilarityResult(**json.load(f))

        # Run plan generation (skip download + analysis)
        plan, plan_cr = generate_plan(analysis, metadata)
        costs.add("plan", plan_cr.model, plan_cr.prompt_tokens, plan_cr.completion_tokens, plan_cr.cost_usd, plan_cr.generation_id)

        result = PipelineResult(
            reel_id=reel_id,
            status=PlanStatus.REVIEW,
            metadata=metadata,
            transcript=transcript,
            analysis=analysis,
            plan=plan,
            similarity=similarity,
            cost_breakdown=costs,
        )

        # Remove the skipped index entry before write_plan adds the real one
        index = get_index()
        index["plans"] = [
            e for e in index["plans"]
            if not (e["reel_id"] == reel_id and e["status"] == PlanStatus.SKIPPED.value)
        ]
        save_index(index)

        write_plan(result)
        costs.resolve_actual_costs()

        base_url = settings.public_url or f"http://{settings.host}:{settings.port}"
        view_url = f"{base_url}/plans/{reel_id}/view"

        action_line = plan.recommended_action or plan.summary
        await query.message.reply_text(
            f"*{_esc(plan.title)}*\n"
            f"{_esc(action_line)}\n\n"
            f"{view_url}",
            parse_mode="Markdown",
        )

        logger.info(f"Telegram: generated plan for {reel_id} (resumed from similarity skip)")

    except Exception as e:
        logger.error(f"Generate-anyway failed for {reel_id}: {e}")
        await query.message.reply_text(f"Failed to generate plan: {e}")


async def _handle_skip_similar(reel_id: str, query) -> None:
    """Confirm skipping a similar reel."""
    await query.edit_message_text(
        f"Skipped: `{reel_id}` -- marked as too similar to existing plans.",
        parse_mode="Markdown",
    )
    logger.info(f"User confirmed skip for similar reel {reel_id}")


def _find_saved_analysis_dir(reel_id: str) -> Path | None:
    """Find the plan directory containing saved analysis for a reel_id."""
    for child in sorted(settings.plans_dir.iterdir(), reverse=True):
        if child.is_dir() and child.name.endswith(f"_{reel_id}"):
            if (child / "analysis.json").exists():
                return child
    return None


_bot_app: Application | None = None
_bot_loop: asyncio.AbstractEventLoop | None = None


def get_bot_app() -> Application | None:
    """Return the running bot Application (or None if not started)."""
    return _bot_app


def get_bot_loop() -> asyncio.AbstractEventLoop | None:
    """Return the event loop the bot is running on (or None if not started)."""
    return _bot_loop


def start_bot():
    """Start the Telegram bot in a background thread."""
    global _bot_app, _bot_loop

    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set, skipping bot startup")
        return

    if not settings.enable_telegram_bot:
        logger.info("ENABLE_TELEGRAM_BOT=false, skipping bot startup (use this in local dev)")
        return

    logger.info("Starting Telegram bot...")

    _bot_app = Application.builder().token(settings.telegram_bot_token).build()
    _bot_app.add_handler(CommandHandler("start", cmd_start))
    _bot_app.add_handler(CommandHandler("status", cmd_status))
    _bot_app.add_handler(CommandHandler("plans", cmd_plans))
    _bot_app.add_handler(CallbackQueryHandler(handle_inline_button))
    _bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    def _run():
        global _bot_loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _bot_loop = loop
        loop.run_until_complete(_bot_app.initialize())
        loop.run_until_complete(_bot_app.start())
        loop.run_until_complete(_bot_app.updater.start_polling(drop_pending_updates=True))
        logger.info("Telegram bot is running")
        loop.run_forever()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


async def stop_bot():
    """Stop the Telegram bot."""
    global _bot_app, _bot_loop
    if _bot_app:
        await _bot_app.updater.stop()
        await _bot_app.stop()
        await _bot_app.shutdown()
        _bot_app = None
        _bot_loop = None
