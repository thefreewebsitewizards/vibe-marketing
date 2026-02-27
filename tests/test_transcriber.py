from src.models import TranscriptResult


def test_transcript_result_model():
    result = TranscriptResult(text="Hello world", language="en", duration=5.0)
    assert result.text == "Hello world"
    assert result.language == "en"
    assert result.duration == 5.0


def test_transcript_result_defaults():
    result = TranscriptResult(text="test")
    assert result.language == "en"
    assert result.duration == 0.0
