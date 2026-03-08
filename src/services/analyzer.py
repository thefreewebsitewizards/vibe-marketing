import json
import base64
from pathlib import Path
from loguru import logger

from src.config import settings
from src.models import (
    ReelMetadata, TranscriptResult, AnalysisResult,
    VideoBreakdown, DetailedNotes, BusinessApplication, FactCheck,
)
from src.prompts.analyze_reel import (
    build_analysis_prompt,
    build_vision_analysis_prompt,
    build_carousel_analysis_prompt,
)
from src.services.llm import chat, ChatResult, get_model_for_step
from src.utils.json_extract import extract_json


def _frames_to_openai_content(frame_paths: list[Path]) -> list[dict]:
    """Convert frame images to OpenAI-compatible content blocks."""
    blocks = []
    for path in frame_paths:
        data = base64.b64encode(path.read_bytes()).decode("utf-8")
        blocks.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{data}"},
        })
    return blocks


def analyze_reel(
    transcript: TranscriptResult,
    metadata: ReelMetadata,
    frame_paths: list[Path] | None = None,
) -> tuple[AnalysisResult, ChatResult]:
    """Analyze a reel transcript (+ optional video frames) with an LLM for business insights."""

    if frame_paths:
        logger.info(f"Sending transcript + {len(frame_paths)} frames for vision analysis...")
        system_prompt, user_content = build_vision_analysis_prompt(
            transcript, metadata, frame_paths
        )
        # Convert Anthropic-style vision blocks to OpenAI-style
        image_blocks = _frames_to_openai_content(frame_paths)
        # The last block from build_vision_analysis_prompt is the text
        text_block = {"type": "text", "text": user_content[-1]["text"]}
        openai_content = image_blocks + [text_block]
    else:
        logger.info("Sending transcript for analysis (no frames)...")
        system_prompt, user_prompt = build_analysis_prompt(transcript, metadata)
        openai_content = user_prompt

    chat_result = chat(system=system_prompt, user_content=openai_content, max_tokens=8192, model_override=get_model_for_step("analysis"))

    # Parse structured JSON from response
    try:
        data = extract_json(chat_result.text, context="analyzer")

        # Parse nested models
        vb_data = data.get("video_breakdown") or {}
        raw_quotes = vb_data.get("key_quotes") or []
        clean_quotes = [q.strip('"\'""''') for q in raw_quotes if isinstance(q, str)]
        video_breakdown = VideoBreakdown(
            hook=vb_data.get("hook") or "",
            main_points=vb_data.get("main_points") or [],
            key_quotes=clean_quotes,
            creator_context=vb_data.get("creator_context") or "",
        )

        detailed_notes_data = data.get("detailed_notes") or {}
        detailed_notes = DetailedNotes(
            what_it_is=detailed_notes_data.get("what_it_is") or "",
            how_useful=detailed_notes_data.get("how_useful") or "",
            how_not_useful=detailed_notes_data.get("how_not_useful") or "",
            target_audience=detailed_notes_data.get("target_audience") or "",
        )

        business_applications = [
            BusinessApplication(
                area=ba.get("area") or "",
                recommendation=ba.get("recommendation") or "",
                target_system=ba.get("target_system") or "general",
                urgency=ba.get("urgency") or "medium",
            )
            for ba in (data.get("business_applications") or [])
        ]

        fact_checks = [
            FactCheck(
                claim=fc.get("claim") or "",
                verdict=fc.get("verdict") or "unverified",
                explanation=fc.get("explanation") or "",
                better_alternative=fc.get("better_alternative") or "",
            )
            for fc in data.get("fact_checks", [])
        ]

        # Normalize swipe_phrases — LLM sometimes returns dicts instead of strings
        raw_phrases = data.get("swipe_phrases", [])
        swipe_phrases = []
        for p in raw_phrases:
            if isinstance(p, str):
                swipe_phrases.append(p)
            elif isinstance(p, dict):
                phrase = p.get("phrase") or p.get("text") or str(p)
                label = p.get("use_for") or p.get("label") or ""
                swipe_phrases.append(f"{phrase} {label}".strip() if label else phrase)

        result = AnalysisResult(
            category=data.get("category", "general"),
            summary=data.get("summary", ""),
            key_insights=data.get("key_insights", []),
            swipe_phrases=swipe_phrases,
            relevance_score=float(data.get("relevance_score", 0.5)),
            raw_response=chat_result.text,
            theme=data.get("theme", ""),
            video_breakdown=video_breakdown,
            detailed_notes=detailed_notes,
            business_applications=business_applications,
            business_impact=data.get("business_impact", ""),
            fact_checks=fact_checks,
        )
    except (json.JSONDecodeError, IndexError, KeyError, ValueError, TypeError) as e:
        logger.warning(f"Failed to parse analysis JSON ({e}), using raw text")
        logger.debug(f"finish_reason={chat_result.finish_reason}, tokens={chat_result.completion_tokens}/{chat_result.total_tokens}")
        raw = chat_result.text
        result = AnalysisResult(
            category="general",
            summary=raw[:500],
            key_insights=[raw],
            relevance_score=0.5,
            raw_response=raw,
            theme="Unparseable response",
            detailed_notes=DetailedNotes(),
            business_impact="Unknown — response could not be parsed",
        )

    logger.info(f"Analysis complete: {result.category} (relevance: {result.relevance_score})")
    return result, chat_result


def analyze_carousel(
    ocr_text: str,
    metadata: ReelMetadata,
    image_paths: list[Path],
) -> tuple[AnalysisResult, ChatResult]:
    """Analyze a carousel post (images + OCR text) with an LLM."""
    logger.info(f"Sending {len(image_paths)} carousel images for analysis...")

    system_prompt, user_content = build_carousel_analysis_prompt(
        ocr_text, metadata, image_paths
    )
    # Convert to OpenAI-style content blocks
    image_blocks = _frames_to_openai_content(image_paths)
    text_block = {"type": "text", "text": user_content[-1]["text"]}
    openai_content = image_blocks + [text_block]

    chat_result = chat(system=system_prompt, user_content=openai_content, max_tokens=8192, model_override=get_model_for_step("analysis"))

    try:
        data = extract_json(chat_result.text, context="carousel_analyzer")

        vb_data = data.get("video_breakdown") or {}
        raw_quotes = vb_data.get("key_quotes") or []
        clean_quotes = [q.strip('"\'""''') for q in raw_quotes if isinstance(q, str)]
        video_breakdown = VideoBreakdown(
            hook=vb_data.get("hook") or "",
            main_points=vb_data.get("main_points") or [],
            key_quotes=clean_quotes,
            creator_context=vb_data.get("creator_context") or "",
        )

        detailed_notes_data = data.get("detailed_notes") or {}
        detailed_notes = DetailedNotes(
            what_it_is=detailed_notes_data.get("what_it_is") or "",
            how_useful=detailed_notes_data.get("how_useful") or "",
            how_not_useful=detailed_notes_data.get("how_not_useful") or "",
            target_audience=detailed_notes_data.get("target_audience") or "",
        )

        business_applications = [
            BusinessApplication(
                area=ba.get("area") or "",
                recommendation=ba.get("recommendation") or "",
                target_system=ba.get("target_system") or "general",
                urgency=ba.get("urgency") or "medium",
            )
            for ba in (data.get("business_applications") or [])
        ]

        fact_checks = [
            FactCheck(
                claim=fc.get("claim") or "",
                verdict=fc.get("verdict") or "unverified",
                explanation=fc.get("explanation") or "",
                better_alternative=fc.get("better_alternative") or "",
            )
            for fc in data.get("fact_checks", [])
        ]

        raw_phrases = data.get("swipe_phrases", [])
        swipe_phrases = []
        for p in raw_phrases:
            if isinstance(p, str):
                swipe_phrases.append(p)
            elif isinstance(p, dict):
                phrase = p.get("phrase") or p.get("text") or str(p)
                label = p.get("use_for") or p.get("label") or ""
                swipe_phrases.append(f"{phrase} {label}".strip() if label else phrase)

        result = AnalysisResult(
            category=data.get("category", "general"),
            summary=data.get("summary", ""),
            key_insights=data.get("key_insights", []),
            swipe_phrases=swipe_phrases,
            relevance_score=float(data.get("relevance_score", 0.5)),
            raw_response=chat_result.text,
            theme=data.get("theme", ""),
            video_breakdown=video_breakdown,
            detailed_notes=detailed_notes,
            business_applications=business_applications,
            business_impact=data.get("business_impact", ""),
            fact_checks=fact_checks,
        )
    except (json.JSONDecodeError, IndexError, KeyError, ValueError, TypeError) as e:
        logger.warning(f"Failed to parse carousel analysis JSON ({e}), using raw text")
        logger.debug(f"finish_reason={chat_result.finish_reason}, tokens={chat_result.completion_tokens}/{chat_result.total_tokens}")
        raw = chat_result.text
        result = AnalysisResult(
            category="general",
            summary=raw[:500],
            key_insights=[raw],
            relevance_score=0.5,
            raw_response=raw,
            theme="Unparseable response",
            detailed_notes=DetailedNotes(),
            business_impact="Unknown — response could not be parsed",
        )

    logger.info(f"Carousel analysis complete: {result.category} (relevance: {result.relevance_score})")
    return result, chat_result
