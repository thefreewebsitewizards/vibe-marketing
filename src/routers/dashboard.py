from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_TEMPLATE = Path(__file__).resolve().parent.parent.parent / "static" / "dashboard.html"


@router.get("/", response_class=HTMLResponse)
def dashboard():
    """Serve the client-rendered dashboard shell."""
    return HTMLResponse(_TEMPLATE.read_text())
