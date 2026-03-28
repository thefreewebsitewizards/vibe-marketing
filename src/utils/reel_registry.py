"""Central reel registry — one JSONL file with all info about every processed reel.

Each line is a self-contained JSON record with analysis, plan, insights, and metadata.
Appended on plan completion. Queryable via GET /reels API.
"""
import json
from datetime import datetime
from pathlib import Path

from loguru import logger

from src.config import settings
from src.models import PipelineResult

_REGISTRY_PATH = Path(settings.plans_dir) / "_reel_registry.jsonl"


def append_reel_entry(result: PipelineResult) -> None:
    """Append a comprehensive reel record to the registry."""
    analysis = result.analysis
    plan = result.plan
    meta = result.metadata
    vb = analysis.video_breakdown

    entry = {
        "reel_id": result.reel_id,
        "url": meta.url,
        "creator": meta.creator,
        "caption": (meta.caption or "")[:500],
        "duration": meta.duration,
        "content_type": meta.content_type,
        "upload_date": meta.upload_date if hasattr(meta, "upload_date") else "",
        "processed_at": datetime.now().isoformat(),
        # Analysis
        "category": analysis.category,
        "theme": analysis.theme,
        "relevance_score": analysis.relevance_score,
        "summary": analysis.summary,
        "business_impact": analysis.business_impact,
        "routing_target": analysis.routing_target,
        # Video content
        "hook": vb.hook,
        "main_points": vb.main_points,
        "key_quotes": vb.key_quotes,
        "creator_context": vb.creator_context,
        # Detailed notes
        "what_it_is": analysis.detailed_notes.what_it_is,
        "how_useful": analysis.detailed_notes.how_useful,
        "how_not_useful": analysis.detailed_notes.how_not_useful,
        "target_audience": analysis.detailed_notes.target_audience,
        # Insights & applications
        "key_insights": analysis.key_insights,
        "business_applications": [
            {
                "area": ba.area,
                "recommendation": ba.recommendation,
                "target_system": ba.target_system,
                "urgency": ba.urgency,
            }
            for ba in analysis.business_applications
        ],
        "reality_checks": [
            {
                "claim": rc.claim,
                "verdict": rc.verdict,
                "explanation": rc.explanation,
            }
            for rc in analysis.reality_checks
        ],
        # Plan
        "plan_title": plan.title,
        "plan_summary": plan.summary,
        "recommended_action": plan.recommended_action,
        "content_angle": plan.content_angle,
        "tasks": [
            {
                "title": t.title,
                "level": t.level,
                "change_type": t.change_type,
                "description": t.description[:300],
            }
            for t in plan.tasks
        ],
        # Content response
        "swipe_phrases": analysis.swipe_phrases,
        "web_design_insights": analysis.web_design_insights,
        # Transcript
        "transcript": result.transcript.text[:2000],
        # Costs
        "total_cost_usd": result.cost_breakdown.total_cost_usd if result.cost_breakdown else 0.0,
    }

    try:
        with open(_REGISTRY_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
        logger.info(f"Reel registry: appended {result.reel_id}")
    except Exception as e:
        logger.error(f"Failed to append reel registry entry: {e}")


def load_registry(limit: int = 0, category: str = "", search: str = "") -> list[dict]:
    """Load registry entries, optionally filtered."""
    if not _REGISTRY_PATH.exists():
        return []

    entries = []
    for line in _REGISTRY_PATH.read_text().strip().split("\n"):
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if category and entry.get("category") != category:
            continue
        if search:
            searchable = json.dumps(entry).lower()
            if search.lower() not in searchable:
                continue

        entries.append(entry)

    # Newest first
    entries.reverse()

    if limit > 0:
        entries = entries[:limit]

    return entries


def registry_stats() -> dict:
    """Quick stats about the registry."""
    entries = load_registry()
    if not entries:
        return {"total": 0}

    categories = {}
    creators = {}
    for e in entries:
        cat = e.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1
        creator = e.get("creator", "unknown")
        creators[creator] = creators.get(creator, 0) + 1

    return {
        "total": len(entries),
        "categories": categories,
        "top_creators": dict(sorted(creators.items(), key=lambda x: -x[1])[:10]),
    }
