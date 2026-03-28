#!/usr/bin/env python3
"""Backfill the reel registry from existing plan directories.

Run once to populate _reel_registry.jsonl from all existing plans.
Safe to re-run — deduplicates by reel_id.
"""
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings

PLANS_DIR = Path(settings.plans_dir)
REGISTRY_PATH = PLANS_DIR / "_reel_registry.jsonl"


def backfill():
    # Load existing registry to avoid duplicates
    existing_ids = set()
    if REGISTRY_PATH.exists():
        for line in REGISTRY_PATH.read_text().strip().split("\n"):
            if line:
                try:
                    existing_ids.add(json.loads(line).get("reel_id", ""))
                except json.JSONDecodeError:
                    pass

    # Find all plan directories
    plan_dirs = sorted(PLANS_DIR.glob("20*_*"))
    added = 0
    skipped = 0

    for plan_dir in plan_dirs:
        analysis_path = plan_dir / "analysis.json"
        metadata_path = plan_dir / "metadata.json"
        plan_json_path = plan_dir / "plan.json"
        transcript_path = plan_dir / "transcript.txt"

        if not analysis_path.exists() or not metadata_path.exists():
            continue

        with open(metadata_path) as f:
            meta = json.load(f)

        reel_id = meta.get("reel_id", "")
        if not reel_id or reel_id in existing_ids:
            skipped += 1
            continue

        with open(analysis_path) as f:
            analysis = json.load(f)

        plan = {}
        if plan_json_path.exists():
            with open(plan_json_path) as f:
                plan = json.load(f)

        transcript = ""
        if transcript_path.exists():
            transcript = transcript_path.read_text()[:2000]

        vb = analysis.get("video_breakdown", {})
        dn = analysis.get("detailed_notes", {})
        cr = analysis.get("content_response", {})

        entry = {
            "reel_id": reel_id,
            "url": meta.get("source_url", ""),
            "creator": meta.get("creator", ""),
            "caption": (meta.get("caption", "") or "")[:500],
            "duration": meta.get("duration", 0),
            "content_type": meta.get("content_type", "reel"),
            "upload_date": "",
            "processed_at": meta.get("created_at", ""),
            "category": analysis.get("category", ""),
            "theme": analysis.get("theme", ""),
            "relevance_score": analysis.get("relevance_score", 0),
            "summary": analysis.get("summary", ""),
            "business_impact": analysis.get("business_impact", ""),
            "routing_target": analysis.get("routing_target", ""),
            "hook": vb.get("hook", ""),
            "main_points": vb.get("main_points", []),
            "key_quotes": vb.get("key_quotes", []),
            "creator_context": vb.get("creator_context", ""),
            "what_it_is": dn.get("what_it_is", ""),
            "how_useful": dn.get("how_useful", ""),
            "how_not_useful": dn.get("how_not_useful", ""),
            "target_audience": dn.get("target_audience", ""),
            "key_insights": analysis.get("key_insights", []),
            "business_applications": [
                {
                    "area": ba.get("area", ""),
                    "recommendation": ba.get("recommendation", ""),
                    "target_system": ba.get("target_system", ""),
                    "urgency": ba.get("urgency", ""),
                }
                for ba in analysis.get("business_applications", [])
            ],
            "reality_checks": [
                {
                    "claim": rc.get("claim", ""),
                    "verdict": rc.get("verdict", ""),
                    "explanation": rc.get("explanation", ""),
                }
                for rc in analysis.get("reality_checks", [])
            ],
            "plan_title": plan.get("title", ""),
            "plan_summary": plan.get("summary", ""),
            "recommended_action": plan.get("recommended_action", ""),
            "content_angle": plan.get("content_angle", ""),
            "tasks": [
                {
                    "title": t.get("title", ""),
                    "level": t.get("level", 1),
                    "change_type": t.get("change_type", ""),
                    "description": t.get("description", "")[:300],
                }
                for t in plan.get("tasks", [])
            ],
            "swipe_phrases": analysis.get("swipe_phrases", []),
            "web_design_insights": analysis.get("web_design_insights", []),
            "transcript": transcript,
            "total_cost_usd": 0,
        }

        with open(REGISTRY_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
        existing_ids.add(reel_id)
        added += 1

    print(f"Backfill complete: {added} added, {skipped} skipped (already in registry or missing data)")
    print(f"Total registry entries: {len(existing_ids)}")


if __name__ == "__main__":
    backfill()
