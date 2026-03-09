import re
import threading
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
from src.models import PipelineResult, PlanStatus, TranscriptResult, CostBreakdown
from src.services.downloader import download_reel, extract_shortcode
from src.services.audio import extract_audio
from src.services.frames import extract_keyframes
from src.services.transcriber import transcribe
from src.services.analyzer import analyze_reel, analyze_carousel
from src.services.ocr import extract_text_from_images
from src.services.planner import generate_plan, check_plan_similarity
from src.services.repurposer import generate_repurposing_plan
from src.services.personal_brand import generate_personal_brand_plan
from src.utils.file_ops import create_temp_dir, cleanup_temp_dir
from src.utils.plan_writer import write_plan
from src.utils.plan_manager import (
    update_plan_status,
    get_plans_by_status,
    get_latest_plan,
    find_plan_by_id,
    is_duplicate,
)

INSTAGRAM_PATTERN = re.compile(r"instagram\.com/(reel|reels|p)/")

# Track last processed reel per chat for quick approve
_last_reel: dict[int, str] = {}
# Track plan message IDs so we can detect replies to plans
_plan_messages: dict[int, str] = {}  # message_id -> reel_id


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
        "Send me an Instagram Reel link and I'll turn it into an actionable business plan.\n\n"
        "Commands:\n"
        "/approve — Approve the last plan (or /approve REEL_ID)\n"
        "/reject — Reject the last plan\n"
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


async def _approve_plan(reel_id: str, reply_fn):
    """Shared approve logic for commands and inline buttons."""
    entry = find_plan_by_id(reel_id)
    if not entry:
        await reply_fn(f"Plan not found: {reel_id}")
        return

    if entry["status"] != "review":
        await reply_fn(f"Plan '{entry['title']}' is already {entry['status']}")
        return

    update_plan_status(reel_id, PlanStatus.APPROVED)
    await reply_fn(
        f"Approved: *{entry['title']}*\n\nStatus is now `approved`. "
        f"Claude Code will pick it up for execution.",
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

    data = query.data  # e.g. "approve:DVO5FbkkWHS" or "reject:DVO5FbkkWHS"
    if ":" not in data:
        return

    action, reel_id = data.split(":", 1)

    async def reply_fn(text, **kwargs):
        await query.edit_message_text(text, **kwargs)

    if action == "approve":
        await _approve_plan(reel_id, reply_fn)
    elif action == "reject":
        await _reject_plan(reel_id, reply_fn)


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

    await update.message.reply_text("Processing your reel... this takes about 60-90 seconds.")

    try:
        temp_dir = create_temp_dir(reel_id)
        costs = CostBreakdown()

        download_result, metadata = download_reel(url, temp_dir)

        if metadata.content_type == "carousel":
            image_paths = download_result
            ocr_text = extract_text_from_images(image_paths)
            transcript = TranscriptResult(text=ocr_text, language="en")
            analysis, analysis_cr = analyze_carousel(ocr_text, metadata, image_paths)
        else:
            video_path = download_result
            audio_path = extract_audio(video_path, temp_dir)
            frame_paths = extract_keyframes(video_path, temp_dir)
            transcript = transcribe(audio_path)
            analysis, analysis_cr = analyze_reel(transcript, metadata, frame_paths)
        costs.add("analysis", analysis_cr.model, analysis_cr.prompt_tokens, analysis_cr.completion_tokens, analysis_cr.cost_usd)

        similarity, sim_cr = check_plan_similarity(analysis)
        if sim_cr:
            costs.add("similarity", sim_cr.model, sim_cr.prompt_tokens, sim_cr.completion_tokens, sim_cr.cost_usd)

        plan, plan_cr = generate_plan(analysis, metadata)
        costs.add("plan", plan_cr.model, plan_cr.prompt_tokens, plan_cr.completion_tokens, plan_cr.cost_usd)

        repurposing_plan, rep_cr = generate_repurposing_plan(analysis, metadata, transcript.text)
        costs.add("repurposing", rep_cr.model, rep_cr.prompt_tokens, rep_cr.completion_tokens, rep_cr.cost_usd)

        personal_brand_plan, pb_cr = generate_personal_brand_plan(analysis, metadata, transcript.text)
        costs.add("personal_brand", pb_cr.model, pb_cr.prompt_tokens, pb_cr.completion_tokens, pb_cr.cost_usd)

        result = PipelineResult(
            reel_id=reel_id,
            status=PlanStatus.REVIEW,
            metadata=metadata,
            transcript=transcript,
            analysis=analysis,
            plan=plan,
            repurposing_plan=repurposing_plan,
            personal_brand_plan=personal_brand_plan,
            similarity=similarity,
            cost_breakdown=costs,
        )
        plan_dir = write_plan(result)
        plan_md_path = plan_dir / "plan.md"

        cleanup_temp_dir(reel_id)

        # Track last reel for this chat
        _last_reel[chat_id] = reel_id

        # Build Telegram summary — lead with video context
        vb = analysis.video_breakdown

        # Video breakdown section
        video_section = ""
        if vb.main_points:
            points = "\n".join(f"  {i}. {_esc(p)}" for i, p in enumerate(vb.main_points, 1))
            video_section = f"*What they talked about:*\n{points}\n\n"
        if vb.key_quotes:
            top_quote = vb.key_quotes[0]
            video_section += f"_{_esc(top_quote)}_\n\n"

        theme_line = f"_{_esc(analysis.theme)}_\n\n" if analysis.theme else ""
        impact_line = f"*Why it matters:* {_esc(analysis.business_impact)}\n\n" if analysis.business_impact else ""

        # Task summary (compact)
        task_lines = []
        for i, t in enumerate(plan.tasks, 1):
            flag = " \\[!]" if t.requires_human else ""
            task_lines.append(f"  {i}. {_esc(t.title)} ({t.estimated_hours:.1f}h){flag}")
        task_list = "\n".join(task_lines)

        human_count = sum(1 for t in plan.tasks if t.requires_human)
        human_note = f"\n{human_count} task(s) need human action \\[!]" if human_count else ""

        # Fact check warnings
        fact_warnings = ""
        flagged = [fc for fc in analysis.fact_checks if fc.verdict in ("outdated", "better_alternative")]
        if flagged:
            warnings = "\n".join(f"  - \\[{_esc(fc.verdict)}] {_esc(fc.claim)}" for fc in flagged)
            fact_warnings = f"\n\n*Heads up — fact checks:*\n{warnings}"

        repurposing_line = ""
        if repurposing_plan and repurposing_plan.tasks:
            repurposing_line = f"\nContent repurposing: {len(repurposing_plan.tasks)} tasks ({repurposing_plan.total_estimated_hours:.1f}h)"

        personal_brand_line = ""
        if personal_brand_plan and personal_brand_plan.tasks:
            personal_brand_line = f"\nDDB personal brand: {len(personal_brand_plan.tasks)} tasks ({personal_brand_plan.total_estimated_hours:.1f}h)"

        similarity_line = ""
        if similarity and similarity.similar_plans:
            top = similarity.similar_plans[0]
            similarity_line = f"\n\n*Similar to:* {_esc(top.title)} ({top.score}% overlap)"
            if similarity.recommendation == "merge":
                similarity_line += " — consider merging tasks"
            elif similarity.recommendation == "skip":
                similarity_line += " — very similar, review carefully"

        cost_line = ""
        if costs.calls:
            details = ", ".join(f"{c.step} ${c.cost_usd:.3f}" for c in costs.calls)
            cost_line = f"\n\nEst\\. cost: ${costs.total_cost_usd:.3f} ({details})"

        summary = (
            f"*{_esc(plan.title)}*\n"
            f"{_esc(metadata.creator)} · {analysis.relevance_score:.0%} relevance\n\n"
            f"{theme_line}"
            f"{video_section}"
            f"{impact_line}"
            f"*Tasks ({plan.total_estimated_hours:.1f}h):*\n"
            f"{task_list}{human_note}{repurposing_line}{personal_brand_line}"
            f"{fact_warnings}"
            f"{similarity_line}"
            f"{cost_line}"
        )

        base_url = settings.public_url or f"http://{settings.host}:{settings.port}"
        view_url = f"{base_url}/plans/{reel_id}/view"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve:{reel_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject:{reel_id}"),
            ],
            [
                InlineKeyboardButton("📄 View Plan", url=view_url),
            ],
        ])

        summary_msg = await update.message.reply_text(
            summary, parse_mode="Markdown", reply_markup=keyboard,
        )

        # Track this message so replies to it trigger refinement
        _plan_messages[summary_msg.message_id] = reel_id

        # Send plan as a document file
        with open(plan_md_path, "rb") as f:
            doc_msg = await update.message.reply_document(
                document=f,
                filename=f"plan_{reel_id}.md",
                caption="Reply to this message with feedback to refine the plan.",
            )
            _plan_messages[doc_msg.message_id] = reel_id

        logger.info(f"Telegram: sent plan for {reel_id}")

    except Exception as e:
        logger.error(f"Telegram pipeline failed: {e}")
        await update.message.reply_text(f"Failed to process reel: {e}")


async def _refine_plan(reel_id: str, feedback: str, update: Update):
    """Regenerate a plan incorporating user feedback."""
    import json
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


def start_bot():
    """Start the Telegram bot in a background thread."""
    global _bot_app

    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set, skipping bot startup")
        return

    logger.info("Starting Telegram bot...")

    _bot_app = Application.builder().token(settings.telegram_bot_token).build()
    _bot_app.add_handler(CommandHandler("start", cmd_start))
    _bot_app.add_handler(CommandHandler("approve", cmd_approve))
    _bot_app.add_handler(CommandHandler("reject", cmd_reject))
    _bot_app.add_handler(CommandHandler("plans", cmd_plans))
    _bot_app.add_handler(CallbackQueryHandler(handle_inline_button))
    _bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    def _run():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_bot_app.initialize())
        loop.run_until_complete(_bot_app.start())
        loop.run_until_complete(_bot_app.updater.start_polling(drop_pending_updates=True))
        logger.info("Telegram bot is running")
        loop.run_forever()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


async def stop_bot():
    """Stop the Telegram bot."""
    global _bot_app
    if _bot_app:
        await _bot_app.updater.stop()
        await _bot_app.stop()
        await _bot_app.shutdown()
        _bot_app = None
