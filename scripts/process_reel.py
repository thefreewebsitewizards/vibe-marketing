#!/usr/bin/env python3
"""CLI script to process a single reel URL through the full pipeline."""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from src.models import PipelineResult, PlanStatus
from src.services.downloader import download_reel, extract_shortcode
from src.services.audio import extract_audio
from src.services.frames import extract_keyframes
from src.services.transcriber import transcribe
from src.services.analyzer import analyze_reel
from src.services.planner import generate_plan
from src.utils.file_ops import create_temp_dir, cleanup_temp_dir
from src.utils.plan_writer import write_plan


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/process_reel.py <instagram_reel_url>")
        sys.exit(1)

    url = sys.argv[1]
    logger.info(f"Processing: {url}")

    reel_id = extract_shortcode(url)
    temp_dir = create_temp_dir(reel_id)

    try:
        # Download
        video_path, metadata = download_reel(url, temp_dir)
        print(f"\n✓ Downloaded: {metadata.creator} ({metadata.duration:.0f}s)")

        # Extract audio + frames
        audio_path = extract_audio(video_path, temp_dir)
        print(f"✓ Audio extracted: {audio_path.name}")

        frame_paths = extract_keyframes(video_path, temp_dir)
        print(f"✓ Extracted {len(frame_paths)} keyframes for vision analysis")

        # Transcribe
        transcript = transcribe(audio_path)
        print(f"✓ Transcribed: {len(transcript.text)} chars")
        print(f"  Preview: {transcript.text[:200]}...")

        # Analyze (with vision if frames available)
        analysis = analyze_reel(transcript, metadata, frame_paths)
        print(f"\n✓ Analysis: {analysis.category} (relevance: {analysis.relevance_score:.0%})")
        print(f"  Summary: {analysis.summary}")
        for insight in analysis.key_insights:
            print(f"  • {insight}")
        if analysis.swipe_phrases:
            print(f"\n✓ Swipe Phrases:")
            for phrase in analysis.swipe_phrases:
                print(f"  ✏️  {phrase}")

        # Generate plan
        plan = generate_plan(analysis, metadata)
        print(f"\n✓ Plan: {plan.title} ({len(plan.tasks)} tasks, {plan.total_estimated_hours:.1f}h)")
        for i, task in enumerate(plan.tasks, 1):
            print(f"  {i}. [{task.priority}] {task.title} ({task.estimated_hours:.1f}h)")

        # Write to plans directory
        result = PipelineResult(
            reel_id=reel_id,
            status=PlanStatus.REVIEW,
            metadata=metadata,
            transcript=transcript,
            analysis=analysis,
            plan=plan,
        )
        plan_dir = write_plan(result)
        print(f"\n✓ Plan saved to: {plan_dir}")

    finally:
        cleanup_temp_dir(reel_id)


if __name__ == "__main__":
    main()
