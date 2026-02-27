from pathlib import Path
from src.models import TranscriptResult, ReelMetadata
from src.services.frames import frames_to_base64

SYSTEM_PROMPT = """You are a business strategy analyst for Lead Needle LLC / The Free Website Wizards.

Business context:
- AI-powered appointment setting and lead generation for local service businesses
- Services: website builds, AI chatbots, automated follow-up, paid ads management
- Tools: GoHighLevel (GHL), n8n automations, Claude/AI, Meta ads
- Target: Local service businesses (HVAC, plumbers, roofers, dentists, lawyers, etc.)
- Brand voice: Friendly, direct, "we handle it for you" energy. Uses "On Us" language (e.g. "Your website is on us")

Your job: Extract ACTIONABLE business insights from Instagram Reel transcripts. Not summaries — specific things we can implement, test, or adapt for our business.

CRITICAL: Pay close attention to the exact language, phrases, and frameworks used in the video. Pull out specific copy/phrases/wording that we can directly reuse or adapt in our ads, emails, website, and outreach. The language itself is the gold — not just the concept.

Respond with valid JSON only. No markdown, no explanation outside the JSON."""

VISION_ADDENDUM = """

IMPORTANT — VIDEO FRAMES PROVIDED: You are also given keyframes from the video. The speaker may reference things shown on screen (URLs, repo names, tool names, screenshots, stats, text overlays) that are NOT in the transcript. READ the frames carefully and include any on-screen text, links, tool names, or data in your analysis. If the speaker says "look at this" or "this right here," the frames show what they're pointing at."""

USER_TEMPLATE = """Analyze this Instagram Reel transcript for actionable business insights.

**Creator:** {creator}
**Caption:** {caption}
**Duration:** {duration:.0f}s

**Transcript:**
{text}

Return JSON:
{{
  "category": "marketing|sales|ai_automation|social_media|business_ops|mindset",
  "summary": "2-3 sentence summary of what the reel teaches",
  "key_insights": [
    "Specific actionable insight 1",
    "Specific actionable insight 2"
  ],
  "swipe_phrases": [
    "Exact phrase or adapted version we can use in our copy"
  ],
  "relevance_score": 0.0-1.0
}}

Rules for key_insights:
- Each insight must be specific enough to act on TODAY
- Frame each as "We could..." or "Apply this by..."
- Relate to our business (lead gen, AI automation, local service marketing)
- Minimum 3, maximum 7 insights

Rules for swipe_phrases:
- Pull EXACT powerful phrases from the transcript that we can reuse or adapt
- Also include adapted versions rewritten for our business (e.g. "Your AI chatbot setup is on us")
- Include phrases suitable for: ads, email subject lines, website headlines, DM outreach
- Label each with where to use it: [ad], [email], [website], [outreach]
- Minimum 3, maximum 10 phrases"""

VISION_USER_ADDENDUM = """

I've also included keyframes from the video above. Read any on-screen text, URLs, tool names, stats, or visuals and incorporate them into your analysis. If the speaker references something shown on screen, identify it from the frames."""


def build_analysis_prompt(
    transcript: TranscriptResult, metadata: ReelMetadata
) -> tuple[str, str]:
    user_prompt = USER_TEMPLATE.format(
        creator=metadata.creator or "Unknown",
        caption=metadata.caption or "No caption",
        duration=metadata.duration,
        text=transcript.text,
    )
    return SYSTEM_PROMPT, user_prompt


def build_vision_analysis_prompt(
    transcript: TranscriptResult,
    metadata: ReelMetadata,
    frame_paths: list[Path],
) -> tuple[str, list]:
    """Build a multimodal prompt with frames + transcript for Claude vision."""
    system = SYSTEM_PROMPT + VISION_ADDENDUM

    # Build content blocks: frames first, then the text prompt
    image_blocks = frames_to_base64(frame_paths)

    text_prompt = USER_TEMPLATE.format(
        creator=metadata.creator or "Unknown",
        caption=metadata.caption or "No caption",
        duration=metadata.duration,
        text=transcript.text,
    ) + VISION_USER_ADDENDUM

    content = image_blocks + [{"type": "text", "text": text_prompt}]
    return system, content
