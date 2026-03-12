"""Read-only API endpoints for dashboard config and stats."""

import json
from pathlib import Path

from fastapi import APIRouter

from src.services.llm import get_model_for_step, MODEL_PRICING
from src.utils.plan_manager import get_index
from src.utils.plan_router import VALID_TARGETS, FALLBACK_MAP

router = APIRouter(prefix="/api")

_PIPELINE_STEPS = [
    "analysis", "plan", "similarity",
]


@router.get("/stats")
def stats():
    """Aggregated counts by status/category, total cost, recent activity."""
    index = get_index()
    plans = index.get("plans", [])

    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    total_cost = 0.0

    for p in plans:
        status = p.get("status", "review")
        by_status[status] = by_status.get(status, 0) + 1
        cat = p.get("category", "general") or "general"
        by_category[cat] = by_category.get(cat, 0) + 1
        total_cost += p.get("estimated_cost", 0)

    recent = list(reversed(plans[-10:])) if plans else []

    return {
        "total": len(plans),
        "by_status": by_status,
        "by_category": by_category,
        "total_cost": round(total_cost, 4),
        "recent": recent,
    }


@router.get("/config/models")
def config_models():
    """LLM model per pipeline step with pricing and override status."""
    result = []
    for step in _PIPELINE_STEPS:
        model = get_model_for_step(step)
        pricing = MODEL_PRICING.get(model, (0, 0))
        result.append({
            "step": step,
            "model": model,
            "prompt_price_per_m": pricing[0],
            "completion_price_per_m": pricing[1],
            "is_override": model != get_model_for_step("__default__"),
        })
    return {"steps": result}


@router.get("/config/capabilities")
def config_capabilities():
    """Load capabilities.json (MCPs + integrations)."""
    caps_path = Path(__file__).resolve().parent.parent.parent / "assets" / "capabilities.json"
    if not caps_path.exists():
        return {"mcps": [], "integrations": []}
    with open(caps_path) as f:
        return json.load(f)


@router.get("/config/routes")
def config_routes():
    """Valid routing targets and category fallback map."""
    return {
        "targets": sorted(VALID_TARGETS),
        "fallback_map": FALLBACK_MAP,
    }
