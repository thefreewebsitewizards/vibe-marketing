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
    update_plan_status,
    get_plans_by_status,
    get_latest_plan,
    find_plan_by_id,
    is_duplicate,
    get_index,
    save_index,
)
from src.utils.feedback import save_feedback, update_feedback_comment

INSTAGRAM_PATTERN = re.compile(r"instagram\.com/(reel|reels|p)/")

# Track last processed reel per chat for quick approve
_last_reel: dict[int, str] = {}
# Track plan message IDs so we can detect replies to plans
_plan_messages: dict[int, str] = {}  # message_id -> reel_id
# Track feedback comment requests: message_id -> reel_id
_feedback_pending_comment: dict[int, str] = {}  # message_id -> reel_id


def _esc(text: str) -> str:
    """Escape Telegram Markdown special characters in dynamic/LLM text."""
    if not text:
        return text
    # Telegram Markdown v1 special chars: * _ ` [
    for ch in ("*", "_", "`", "["):
        text = text.replace(ch, "\\" + ch)
    return text


def _format_cost_line(costs: CostBreakdown) -> str:
    """Format cost breakdown for Telegram message."""
    lines = []
    for c in costs.calls:
        step = _esc(c.step)
        model_short = _esc(c.model.split("/")[-1]) if c.model else "?"
        actual = f" → ${c.actual_cost_usd:.4f}" if c.actual_cost_usd is not None else ""
        lines.append(f"  {step}: ${c.cost_usd:.4f}{actual} ({model_short}, {c.prompt_tokens + c.completion_tokens:,}tok)")

    detail_text = "\n".join(lines)

    if costs.total_actual_cost_usd is not None:
        total_line = f"*Cost:* ${costs.total_actual_cost_usd:.4f} actual (${costs.total_cost_usd:.4f} est\\.)"
    else:
        total_line = f"*Cost:* ${costs.total_cost_usd:.4f} est\\."

    return f"\n\n{total_line}\n{detail_text}"


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me an Instagram Reel link and I'll turn it into an actionable business plan.\n\n"
        "Commands:\n"
        "/approve — Approve the last plan (or /approve REEL_ID)\n"
        "/reject — Reject the last plan\n"
        "/done — Mark human tasks complete (or /done REEL_ID)\n"
        "/status — Show execution summary of all plans\n"
        "/plans — Show all plans and their status\n\n"
        "You can also tap the buttons under each plan, or reply to a plan with feedback to refine it."
    )


async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Approve a plan for execution. Usage: /approve or /approve REEL_ID"""
    chat_id = update.message.chat.id
    args = context.args

    if args:
        reel_id = args[0]
    elif chat_id in _last_reel:
        reel_id = _last_reel[chat_id]
    else:
        latest = get_latest_plan()
        if latest and latest["status"] == "review":
            reel_id = latest["reel_id"]
        else:
            await update.message.reply_text("No plan to approve. Send a reel first or use /approve REEL_ID")
            return

    await _approve_plan(reel_id, update.message.reply_text)


async def cmd_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reject a plan. Usage: /reject or /reject REEL_ID"""
    chat_id = update.message.chat.id
    args = context.args

    if args:
        reel_id = args[0]
    elif chat_id in _last_reel:
        reel_id = _last_reel[chat_id]
    else:
        latest = get_latest_plan()
        if latest and latest["status"] == "review":
            reel_id = latest["reel_id"]
        else:
            await update.message.reply_text("No plan to reject. Use /reject REEL_ID")
            return

    await _reject_plan(reel_id, update.message.reply_text)


async def _approve_plan(reel_id: str, reply_fn, level: int | None = None):
    """Shared approve logic for commands and inline buttons."""
    entry = find_plan_by_id(reel_id)
    if not entry:
        await reply_fn(f"Plan not found: {reel_id}")
        return

    if entry["status"] != "review":
        await reply_fn(f"Plan '{entry['title']}' is already {entry['status']}")
        return

    # Store approved level in the plan metadata
    if level:
        try:
            plan_dir = settings.plans_dir / entry["plan_dir"]
            meta_path = plan_dir / "metadata.json"
            if meta_path.exists():
                with open(meta_path) as f:
                    meta = json.load(f)
                meta["approved_level"] = level
                with open(meta_path, "w") as f:
                    json.dump(meta, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save approved level: {e}")

    level_label = {1: "L1 Note it", 2: "L2 Build it", 3: "L3 Go deep"}.get(level, "all")

    update_plan_status(reel_id, PlanStatus.APPROVED)
    await reply_fn(
        f"Approved: *{_esc(entry['title'])}* ({level_label})\n\n"
        f"Executing tasks up to level {level or 'all'}.",
        parse_mode="Markdown",
    )


async def _reject_plan(reel_id: str, reply_fn):
    """Shared reject logic for commands and inline buttons."""
    entry = find_plan_by_id(reel_id)
    if not entry:
        await reply_fn(f"Plan not found: {reel_id}")
        return

    update_plan_status(reel_id, PlanStatus.FAILED)
    await reply_fn(f"Rejected: *{entry['title']}*", parse_mode="Markdown")


async def handle_inline_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard button presses (approve/reject)."""
    query = update.callback_query
    await query.answer()

    data = query.data  # e.g. "approve:DVO5FbkkWHS:2" or "reject:DVO5FbkkWHS"
    if ":" not in data:
        return

    parts = data.split(":")
    action = parts[0]
    reel_id = parts[1] if len(parts) > 1 else ""

    async def reply_fn(text, **kwargs):
        await query.edit_message_text(text, **kwargs)

    if action == "approve":
        level = int(parts[2]) if len(parts) > 2 else None
        await _approve_plan(reel_id, reply_fn, level=level)
    elif action == "reject":
        await _reject_plan(reel_id, reply_fn)
    elif action == "generate_anyway":
        await _handle_generate_anyway(reel_id, query)
    elif action == "skip_similar":
        await _handle_skip_similar(reel_id, query)
    elif action in ("feedback_good", "feedback_bad", "feedback_partial"):
        rating = action.replace("feedback_", "")
        await _handle_feedback(reel_id, rating, query)


async def _handle_feedback(reel_id: str, rating: str, query):
    """Save feedback rating and optionally prompt for a comment."""
    label = {"good": "Good", "bad": "Needs Work", "partial": "Partial"}.get(rating, rating)
    save_feedback(reel_id, rating)

    if rating in ("bad", "partial"):
        prompt_msg = await query.message.reply_text(
            f"Feedback saved as *{_esc(label)}*.\n\n"
            f"Reply to this message with details on what should be different.",
            parse_mode="Markdown",
        )
        _feedback_pending_comment[prompt_msg.message_id] = reel_id
    else:
        await query.message.reply_text(f"Thanks! Feedback saved as *{_esc(label)}*.", parse_mode="Markdown")

    logger.info(f"Feedback recorded for {reel_id}: {rating}")


async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mark human tasks as done. Usage: /done or /done REEL_ID"""
    chat_id = update.message.chat.id
    args = context.args

    if args:
        reel_id = args[0]
    elif chat_id in _last_reel:
        reel_id = _last_reel[chat_id]
    else:
        await update.message.reply_text("Usage: /done REEL_ID")
        return

    entry = find_plan_by_id(reel_id)
    if not entry:
        await update.message.reply_text(f"Plan not found: {reel_id}")
        return

    if entry["status"] != "in_progress":
        await update.message.reply_text(f"Plan '{entry['title']}' is {entry['status']}, not in_progress")
        return

    update_plan_status(reel_id, PlanStatus.COMPLETED)
    await update.message.reply_text(
        f"Completed: *{entry['title']}*\n\nAll tasks done.",
        parse_mode="Markdown",
    )


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

    # Check if this is a reply to a feedback prompt (save comment)
    if update.message.reply_to_message and update.message.reply_to_message.message_id in _feedback_pending_comment:
        reel_id = _feedback_pending_comment.pop(update.message.reply_to_message.message_id)
        if update_feedback_comment(reel_id, text):
            await update.message.reply_text("Feedback comment saved. Thanks!")
        else:
            await update.message.reply_text("Could not save feedback comment — plan not found.")
        return

    # Check if this is a reply to a plan message (refinement flow)
    if update.message.reply_to_message and update.message.reply_to_message.message_id in _plan_messages:
        reel_id = _plan_messages[update.message.reply_to_message.message_id]
        await _refine_plan(reel_id, text, update)
        return

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
        status = entry["status"] if entry else "unknown"
        await update.message.reply_text(
            f"This reel (`{reel_id}`) has already been processed.\n"
            f"Status: *{status}*\n\n"
            f"Use /plans to view it, or send a different reel.",
            parse_mode="Markdown",
        )
        return

    t0 = time.monotonic()
    total_steps = 4
    progress_msg = await update.message.reply_text(
        f"Downloading reel... (step 1/{total_steps})"
    )

    async def _progress(step: int, label: str):
        elapsed = int(time.monotonic() - t0)
        try:
            await progress_msg.edit_text(
                f"{label} (step {step}/{total_steps}, {elapsed}s elapsed)"
            )
        except Exception:
            pass  # edit can fail if text unchanged or rate-limited

    try:
        temp_dir = create_temp_dir(reel_id)
        costs = CostBreakdown()

        download_result, metadata = download_reel(url, temp_dir)

        if metadata.content_type == "carousel":
            await _progress(2, "Reading carousel images...")
            image_paths = download_result
            ocr_text = extract_text_from_images(image_paths)
            transcript = TranscriptResult(text=ocr_text, language="en")
            await _progress(3, "Analyzing content...")
            analysis, analysis_cr = analyze_carousel(ocr_text, metadata, image_paths, user_context=user_context)
        else:
            await _progress(2, "Transcribing & analyzing...")
            video_path = download_result
            audio_path = extract_audio(video_path, temp_dir)
            frame_paths = extract_keyframes(video_path, temp_dir)
            transcript = transcribe(audio_path)
            await _progress(3, "Analyzing content...")
            analysis, analysis_cr = analyze_reel(transcript, metadata, frame_paths, user_context=user_context)
        costs.add("analysis", analysis_cr.model, analysis_cr.prompt_tokens, analysis_cr.completion_tokens, analysis_cr.cost_usd, analysis_cr.generation_id)

        similarity, sim_cr = check_plan_similarity(analysis)
        if sim_cr:
            costs.add("similarity", sim_cr.model, sim_cr.prompt_tokens, sim_cr.completion_tokens, sim_cr.cost_usd, sim_cr.generation_id)

        if similarity.recommendation == "skip" or similarity.max_score > 70:
            _save_analysis_for_resume_telegram(reel_id, analysis, metadata, similarity, costs, transcript)
            await _send_similarity_notification(update, reel_id, analysis, similarity, costs)
            cleanup_temp_dir(reel_id)
            return

        await _progress(4, "Generating plan...")
        plan, plan_cr = generate_plan(analysis, metadata, user_context=user_context)
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
        plan_dir = write_plan(result)
        plan_md_path = plan_dir / "plan.md"

        cleanup_temp_dir(reel_id)

        # Track last reel for this chat
        _last_reel[chat_id] = reel_id

        # Build concise Telegram summary with tiered levels
        theme_line = f"_{_esc(analysis.theme)}_" if analysis.theme else ""

        # Level summaries
        level_lines = []
        for lvl in (1, 2, 3):
            lvl_tasks = [t for t in plan.tasks if t.level == lvl]
            lvl_summary = plan.level_summaries.get(str(lvl), "")
            if lvl_tasks or lvl_summary:
                hours = sum(t.estimated_hours for t in lvl_tasks)
                human = any(t.requires_human for t in lvl_tasks)
                flag = " \\[!]" if human else ""
                label = _esc(lvl_summary) if lvl_summary else _esc(lvl_tasks[0].title) if lvl_tasks else ""
                level_lines.append(f"  L{lvl}: {label} ({hours:.1f}h){flag}")

        levels_section = "\n".join(level_lines)

        # Content angle
        content_line = ""
        if plan.content_angle:
            content_line = f"\n\nDDB angle: {_esc(plan.content_angle)}"

        # Fact check warnings (only if flagged)
        fact_warnings = ""
        flagged = [fc for fc in analysis.fact_checks if fc.verdict in ("outdated", "better_alternative")]
        if flagged:
            warnings = "\n".join(f"  \\[{_esc(fc.verdict)}] {_esc(fc.claim)}" for fc in flagged)
            fact_warnings = f"\n\n{warnings}"

        # Resolve actual costs
        costs.resolve_actual_costs()

        summary = (
            f"*{_esc(plan.title)}*\n"
            f"{_esc(metadata.creator)} · {analysis.relevance_score:.0%}\n"
            f"{theme_line}\n\n"
            f"*Pick a level:*\n"
            f"{levels_section}"
            f"{content_line}"
            f"{fact_warnings}"
        )

        base_url = settings.public_url or f"http://{settings.host}:{settings.port}"
        view_url = f"{base_url}/plans/{reel_id}/view"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("L1 Note it", callback_data=f"approve:{reel_id}:1"),
                InlineKeyboardButton("L2 Build it", callback_data=f"approve:{reel_id}:2"),
                InlineKeyboardButton("L3 Go deep", callback_data=f"approve:{reel_id}:3"),
            ],
            [
                InlineKeyboardButton("❌ Skip", callback_data=f"reject:{reel_id}"),
                InlineKeyboardButton("📄 Details", url=view_url),
            ],
            [
                InlineKeyboardButton("👍", callback_data=f"feedback_good:{reel_id}"),
                InlineKeyboardButton("👎", callback_data=f"feedback_bad:{reel_id}"),
            ],
        ])

        # Delete progress message before sending summary
        elapsed = int(time.monotonic() - t0)
        try:
            await progress_msg.delete()
        except Exception:
            pass

        cost_line = _format_cost_line(costs)
        summary_with_meta = f"{summary}{cost_line}\n\n_{elapsed}s_"

        summary_msg = await update.message.reply_text(
            summary_with_meta, parse_mode="Markdown", reply_markup=keyboard,
        )

        # Track this message so replies to it trigger refinement
        _plan_messages[summary_msg.message_id] = reel_id

        # Send plan as a document file
        with open(plan_md_path, "rb") as f:
            doc_msg = await update.message.reply_document(
                document=f,
                filename=f"plan_{reel_id}.md",
                caption="Reply with feedback to refine.",
            )
            _plan_messages[doc_msg.message_id] = reel_id

        logger.info(f"Telegram: sent plan for {reel_id} in {elapsed}s")

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

        result_plan_dir = write_plan(result)
        plan_md_path = result_plan_dir / "plan.md"

        # Build concise summary with tiered levels
        costs.resolve_actual_costs()
        cost_line = _format_cost_line(costs) if costs.calls else ""

        theme_line = f"_{_esc(analysis.theme)}_" if analysis.theme else ""

        level_lines = []
        for lvl in (1, 2, 3):
            lvl_tasks = [t for t in plan.tasks if t.level == lvl]
            lvl_summary = plan.level_summaries.get(str(lvl), "")
            if lvl_tasks or lvl_summary:
                hours = sum(t.estimated_hours for t in lvl_tasks)
                label = _esc(lvl_summary) if lvl_summary else _esc(lvl_tasks[0].title) if lvl_tasks else ""
                level_lines.append(f"  L{lvl}: {label} ({hours:.1f}h)")
        levels_section = "\n".join(level_lines)

        summary = (
            f"*{_esc(plan.title)}*\n"
            f"{_esc(metadata.creator)} · {analysis.relevance_score:.0%}\n"
            f"{theme_line}\n\n"
            f"*Pick a level:*\n"
            f"{levels_section}"
            f"{cost_line}"
        )

        base_url = settings.public_url or f"http://{settings.host}:{settings.port}"
        view_url = f"{base_url}/plans/{reel_id}/view"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("L1 Note it", callback_data=f"approve:{reel_id}:1"),
                InlineKeyboardButton("L2 Build it", callback_data=f"approve:{reel_id}:2"),
                InlineKeyboardButton("L3 Go deep", callback_data=f"approve:{reel_id}:3"),
            ],
            [
                InlineKeyboardButton("❌ Skip", callback_data=f"reject:{reel_id}"),
                InlineKeyboardButton("📄 Details", url=view_url),
            ],
        ])

        summary_msg = await query.message.reply_text(
            summary, parse_mode="Markdown", reply_markup=keyboard,
        )
        _plan_messages[summary_msg.message_id] = reel_id

        with open(plan_md_path, "rb") as f:
            doc_msg = await query.message.reply_document(
                document=f,
                filename=f"plan_{reel_id}.md",
                caption="Reply to this message with feedback to refine the plan.",
            )
            _plan_messages[doc_msg.message_id] = reel_id

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


async def _refine_plan(reel_id: str, feedback: str, update: Update):
    """Regenerate a plan incorporating user feedback."""
    from src.config import settings as cfg

    entry = find_plan_by_id(reel_id)
    if not entry:
        await update.message.reply_text(f"Can't find plan for {reel_id}")
        return

    plan_dir = cfg.plans_dir / entry["plan_dir"]
    analysis_path = plan_dir / "analysis.json"
    metadata_path = plan_dir / "metadata.json"

    if not analysis_path.exists():
        await update.message.reply_text("Original analysis not found — can't refine.")
        return

    await update.message.reply_text(f"Refining plan with your feedback... one moment.")

    try:
        from src.models import AnalysisResult, ReelMetadata

        with open(analysis_path) as f:
            analysis_data = json.load(f)
        analysis = AnalysisResult(**analysis_data)

        with open(metadata_path) as f:
            meta_data = json.load(f)
        metadata = ReelMetadata(
            url=meta_data.get("source_url", ""),
            shortcode=reel_id,
            creator=meta_data.get("creator", ""),
            caption="",
        )

        # Append feedback to analysis insights so the planner sees it
        analysis.key_insights.append(f"USER FEEDBACK (must incorporate): {feedback}")

        plan, _ = generate_plan(analysis, metadata)

        # Overwrite the plan file
        from src.utils.plan_writer import write_plan_md
        plan_md_path = plan_dir / "plan.md"
        write_plan_md(plan, plan_md_path)

        chat_id = update.message.chat.id
        _last_reel[chat_id] = reel_id

        task_lines = []
        for i, t in enumerate(plan.tasks, 1):
            flag = " \\[!]" if t.requires_human else ""
            task_lines.append(f"  {i}. \\[{_esc(t.priority)}] {_esc(t.title)} ({t.estimated_hours:.1f}h){flag}")
        task_list = "\n".join(task_lines)

        human_count = sum(1 for t in plan.tasks if t.requires_human)
        human_note = f"\n{human_count} task(s) need human action \\[!]" if human_count else ""

        summary = (
            f"*Refined: {_esc(plan.title)}*\n\n"
            f"{_esc(plan.summary)}\n\n"
            f"*Tasks ({plan.total_estimated_hours:.1f}h total):*\n"
            f"{task_list}{human_note}"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve:{reel_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject:{reel_id}"),
            ]
        ])

        summary_msg = await update.message.reply_text(
            summary, parse_mode="Markdown", reply_markup=keyboard,
        )
        _plan_messages[summary_msg.message_id] = reel_id

        with open(plan_md_path, "rb") as f:
            doc_msg = await update.message.reply_document(
                document=f,
                filename=f"plan_{reel_id}_refined.md",
                caption="Refined plan — reply again or approve/reject.",
            )
            _plan_messages[doc_msg.message_id] = reel_id

        logger.info(f"Telegram: refined plan for {reel_id}")

    except Exception as e:
        logger.error(f"Plan refinement failed: {e}")
        await update.message.reply_text(f"Refinement failed: {e}")


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
    _bot_app.add_handler(CommandHandler("approve", cmd_approve))
    _bot_app.add_handler(CommandHandler("reject", cmd_reject))
    _bot_app.add_handler(CommandHandler("done", cmd_done))
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
