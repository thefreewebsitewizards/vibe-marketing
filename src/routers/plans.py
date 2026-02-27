from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.models import PlanStatus
from src.services.executor import (
    get_approved_plans,
    load_plan,
    get_execution_summary,
)
from src.utils.plan_manager import update_plan_status, get_plans_by_status

router = APIRouter(prefix="/plans")


class StatusUpdate(BaseModel):
    status: PlanStatus


@router.get("/")
def list_plans():
    """List all plans grouped by status."""
    result = {}
    for status in PlanStatus:
        plans = get_plans_by_status(status)
        if plans:
            result[status.value] = plans
    return result


@router.get("/approved")
def list_approved():
    """Get all approved plans ready for execution."""
    return get_approved_plans()


@router.get("/{reel_id}")
def get_plan(reel_id: str):
    """Get full plan data for a specific reel."""
    from src.utils.plan_manager import find_plan_by_id
    entry = find_plan_by_id(reel_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Plan not found: {reel_id}")
    return load_plan(entry["plan_dir"])


@router.patch("/{reel_id}/status")
def update_status(reel_id: str, body: StatusUpdate):
    """Update a plan's status."""
    updated = update_plan_status(reel_id, body.status)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Plan not found: {reel_id}")
    return {"reel_id": reel_id, "status": body.status.value}


@router.get("/summary/all")
def summary():
    """Get a text summary of all plans."""
    return {"summary": get_execution_summary()}
