import json
from pathlib import Path
import anthropic
from loguru import logger

from src.config import settings
from src.models import ReelMetadata, TranscriptResult, AnalysisResult
from src.prompts.analyze_reel import build_analysis_prompt, build_vision_analysis_prompt
from src.services.frames import frames_to_base64


def analyze_reel(
    transcript: TranscriptResult,
    metadata: ReelMetadata,
    frame_paths: list[Path] | None = None,
) -> AnalysisResult:
    """Analyze a reel transcript (+ optional video frames) with Claude for business insights."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    if frame_paths:
        logger.info(f"Sending transcript + {len(frame_paths)} frames to Claude for vision analysis...")
        system_prompt, user_content = build_vision_analysis_prompt(
            transcript, metadata, frame_paths
        )
    else:
        logger.info("Sending transcript to Claude for analysis (no frames)...")
        system_prompt, user_prompt = build_analysis_prompt(transcript, metadata)
        user_content = user_prompt

    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=2000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )

    raw = response.content[0].text

    # Parse structured JSON from response
    try:
        json_text = raw
        if "```json" in raw:
            json_text = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            json_text = raw.split("```")[1].split("```")[0]

        data = json.loads(json_text)
        result = AnalysisResult(
            category=data.get("category", "general"),
            summary=data.get("summary", ""),
            key_insights=data.get("key_insights", []),
            swipe_phrases=data.get("swipe_phrases", []),
            relevance_score=float(data.get("relevance_score", 0.5)),
            raw_response=raw,
        )
    except (json.JSONDecodeError, IndexError, KeyError):
        logger.warning("Failed to parse structured response, using raw text")
        result = AnalysisResult(
            category="general",
            summary=raw[:500],
            key_insights=[raw],
            relevance_score=0.5,
            raw_response=raw,
        )

    logger.info(f"Analysis complete: {result.category} (relevance: {result.relevance_score})")
    return result
