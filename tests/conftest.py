import pytest
from pathlib import Path


@pytest.fixture
def tmp_plans_dir(tmp_path):
    """Provide a temporary plans directory."""
    plans = tmp_path / "plans"
    plans.mkdir()
    return plans


@pytest.fixture
def sample_reel_urls():
    return [
        "https://www.instagram.com/reel/ABC123def/",
        "https://instagram.com/reel/XYZ789/",
        "https://www.instagram.com/reels/SHORT1/",
        "https://www.instagram.com/p/POST123/",
    ]
