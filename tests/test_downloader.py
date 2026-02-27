import pytest
from src.services.downloader import extract_shortcode


def test_extract_shortcode_reel():
    assert extract_shortcode("https://www.instagram.com/reel/ABC123def/") == "ABC123def"


def test_extract_shortcode_reels():
    assert extract_shortcode("https://instagram.com/reels/XYZ789/") == "XYZ789"


def test_extract_shortcode_post():
    assert extract_shortcode("https://www.instagram.com/p/POST123/") == "POST123"


def test_extract_shortcode_with_query_params():
    url = "https://www.instagram.com/reel/ABC123/?igsh=abc"
    assert extract_shortcode(url) == "ABC123"


def test_extract_shortcode_invalid():
    with pytest.raises(ValueError):
        extract_shortcode("https://example.com/not-instagram")


def test_extract_shortcode_empty():
    with pytest.raises(ValueError):
        extract_shortcode("")
