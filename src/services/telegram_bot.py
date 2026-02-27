import re
import threading
from pathlib import Path
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from loguru import logger

from src.config import settings
from src.models import PipelineResult, PlanStatus
from src.services.downloader import download_reel, extract_shortcode
from src.services.audio import extract_audio
from src.services.frames import extract_keyframes
from src.services.transcriber import transcribe
from src.services.analyzer import analyze_reel
from src.services.planner import generate_plan
from src.utils.file_ops import create_temp_dir, cleanup_temp_dir
from src.utils.plan_writer import write_plan

INSTAGRAM_PATTERN = re.compile(r"instagram\.com/(reel|reels|p)/")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me an Instagram Reel link and I'll turn it into an actionable business plan."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    if not INSTAGRAM_PATTERN.search(text):
        await update.message.reply_text(
            "Send me an Instagram Reel URL (instagram.com/reel/...)"
        )
        return

    url_match = re.search(r"https?://[^\s]+instagram\.com/[^\s]+", text)
    url = url_match.group(0) if url_match else text

    await update.message.reply_text("Processing your reel... this takes about 60-90 seconds.")

    try:
        reel_id = extract_shortcode(url)
        temp_dir = create_temp_dir(reel_id)

        video_path, metadata = download_reel(url, temp_dir)
        audio_path = extract_audio(video_path, temp_dir)
        frame_paths = extract_keyframes(video_path, temp_dir)
        transcript = transcribe(audio_path)
        analysis = analyze_reel(transcript, metadata, frame_paths)
        plan = generate_plan(analysis, metadata)

        result = PipelineResult(
            reel_id=reel_id,
            status=PlanStatus.REVIEW,
            metadata=metadata,
            transcript=transcript,
            analysis=analysis,
            plan=plan,
        )
        plan_dir = write_plan(result)
        plan_md_path = plan_dir / "plan.md"

        cleanup_temp_dir(reel_id)

        # Send short summary
        task_list = "\n".join(
            f"  {i}. [{t.priority}] {t.title} ({t.estimated_hours:.1f}h)"
            for i, t in enumerate(plan.tasks, 1)
        )
        summary = (
            f"*{plan.title}*\n\n"
            f"{plan.summary}\n\n"
            f"*Tasks ({plan.total_estimated_hours:.1f}h total):*\n"
            f"{task_list}\n\n"
            f"Relevance: {analysis.relevance_score:.0%}\n\n"
            f"_Full plan attached as file. Reply with changes or send another reel._"
        )
        await update.message.reply_text(summary, parse_mode="Markdown")

        # Send plan as a document file
        with open(plan_md_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=f"plan_{reel_id}.md",
                caption="Full implementation plan",
            )

        logger.info(f"Telegram: sent plan for {reel_id}")

    except Exception as e:
        logger.error(f"Telegram pipeline failed: {e}")
        await update.message.reply_text(f"Failed to process reel: {e}")


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
    _bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    def _run():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_bot_app.initialize())
        loop.run_until_complete(_bot_app.start())
        loop.run_until_complete(_bot_app.updater.start_polling())
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
