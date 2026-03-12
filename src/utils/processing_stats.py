"""Track processing times to provide accurate estimates."""
import json
from pathlib import Path
from loguru import logger

from src.config import settings

_DEFAULT_ESTIMATE = 55  # seconds, conservative default


def _stats_path() -> Path:
    return settings.plans_dir / "_stats.json"


def _load() -> dict:
    path = _stats_path()
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {"times": [], "avg": _DEFAULT_ESTIMATE}


def _save(stats: dict) -> None:
    path = _stats_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(stats, f, indent=2)


def get_estimate() -> int:
    """Get estimated processing time in seconds."""
    stats = _load()
    return int(stats.get("avg", _DEFAULT_ESTIMATE))


def record_time(seconds: float) -> None:
    """Record a processing time and update the rolling average."""
    stats = _load()
    times = stats.get("times", [])
    times.append(round(seconds, 1))
    # Keep last 20 runs
    times = times[-20:]
    avg = sum(times) / len(times)
    stats["times"] = times
    stats["avg"] = round(avg, 1)
    _save(stats)
    logger.debug(f"Processing stats: {seconds:.0f}s this run, {avg:.0f}s avg ({len(times)} samples)")
