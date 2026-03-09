from pathlib import Path

from src.models import TranscriptResult, ReelMetadata
from src.services.frames import frames_to_base64
from src.utils.feedback import get_recent_feedback

SYSTEM_PROMPT = """You are a business strategy analyst for Lead Needle LLC / The Free Website Wizards.

Business context:
- AI-powered appointment setting and lead generation for local service businesses
- Services: website builds, AI chatbots, automated follow-up, paid ads management
- Tools: GoHighLevel (GHL), n8n automations, Claude/AI, Meta ads
- Target: Local service businesses (HVAC, plumbers, roofers, dentists, lawyers, etc.)
- Brand voice: Friendly, direct, "we handle it for you" energy. Uses "On Us" language (e.g. "Your website is on us")

Your job: Extract ACTIONABLE business insights from Instagram Reel transcripts. Not summaries — specific things we can implement, test, or adapt for our business.

CRITICAL: Pay close attention to the exact language, phrases, and frameworks used in the video. Pull out specific copy/phrases/wording that we can directly reuse or adapt in our ads, emails, website, and outreach. The language itself is the gold — not just the concept.

Category-specific guidelines:
- IF marketing/copywriting: Identify the psychological principle (urgency, authority, social proof, scarcity, consistency bias). Swipe phrases MUST include the principle being leveraged.
- IF sales: Extract exact dialogue snippets and conversation frameworks. Note emotional triggers used.
- IF ai_automation: Name the specific tools, APIs, code patterns, or repos shown/mentioned. Be technically precise about what's possible.
- IF social_media: Focus on hooks, format patterns, and engagement mechanics — not just topic.

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
  "theme": "One sentence (max 15 words) describing the core idea — for quick scanning",
  "summary": "2-3 sentence summary of what the reel teaches",
  "video_breakdown": {{
    "hook": "How the video opens — what grabs attention in the first 3 seconds",
    "main_points": [
      "First key point the creator makes (in order they appear)",
      "Second key point...",
      "Third key point..."
    ],
    "key_quotes": [
      "Exact notable quote from the transcript worth remembering",
      "Another powerful or memorable line"
    ],
    "creator_context": "Who this creator is (if recognizable) and why their perspective/authority matters for this topic"
  }},
  "detailed_notes": {{
    "what_it_is": "What this reel is about and what strategy/tactic it presents",
    "how_useful": "How this specifically helps Lead Needle / Free Website Wizards",
    "how_not_useful": "What doesn't apply or where the advice falls short for us",
    "target_audience": "Who on our team should see this (e.g. Dylan for sales, dev for automations)"
  }},
  "key_insights": [
    "Specific actionable insight 1",
    "Specific actionable insight 2"
  ],
  "business_applications": [
    {{
      "area": "What area this applies to (e.g. lead nurture, ad copy, onboarding)",
      "recommendation": "Specific action to take",
      "target_system": "ghl|n8n|sales_script|website|meta_ads|telegram|general",
      "urgency": "high|medium|low"
    }}
  ],
  "business_impact": "One sentence on how this affects our bottom line if implemented",
  "swipe_phrases": [
    "Exact phrase or adapted version we can use in our copy"
  ],
  "fact_checks": [
    {{
      "claim": "A specific claim or stat from the reel",
      "verdict": "verified|outdated|better_alternative|unverified",
      "explanation": "Why this verdict",
      "better_alternative": "If outdated or better_alternative, what to use instead"
    }}
  ],
  "routing_target": "claude-upgrades|ddb|tfww|n8n-automations|ghl-fix|aias",
  "relevance_score": 0.0-1.0
}}

Rules for routing_target — pick the SINGLE best folder for this reel's content:
- "claude-upgrades" = AI tool improvements, Claude/LLM workflow upgrades, prompt engineering
- "ddb" = Dylan Does Business — social media content, personal brand, content creation
- "tfww" = The Free Website Wizards — sales, marketing, business ops, client acquisition, email/SMS
- "n8n-automations" = n8n workflow automations, API integrations, backend automations
- "ghl-fix" = GoHighLevel configuration, CRM setup, pipeline/funnel fixes
- "aias" = AI appointment setting — AI chatbots, conversational AI, booking flows
- If the reel spans multiple areas, pick the PRIMARY one that best matches the core topic

Rules for video_breakdown:
- Write main_points as if you're taking notes on the video for someone who hasn't watched it
- Order main_points chronologically (how the creator presents them)
- key_quotes must be EXACT words from the transcript, not paraphrased
- For creator_context, note their niche, follower count if mentioned, or relevant credentials
- Minimum 3 main_points, maximum 6
- Minimum 2 key_quotes, maximum 5

Rules for key_insights:
- Each insight must be specific enough to act on TODAY
- Frame each as "We could..." or "Apply this by..."
- Relate to our business (lead gen, AI automation, local service marketing)
- When the reel names specific tools, APIs, repos, or URLs — include them by name
- Minimum 3, maximum 7 insights

Rules for business_applications:
- Each must name a specific target_system we'd implement it in
- urgency "high" = do this week, "medium" = this month, "low" = backlog
- Minimum 1, maximum 5 applications

Rules for swipe_phrases:
- Pull EXACT powerful phrases from the transcript that we can reuse or adapt
- Also include adapted versions rewritten for our business (e.g. "Your AI chatbot setup is on us")
- Include phrases suitable for: ads, email subject lines, website headlines, DM outreach
- Label each with where to use it: [ad], [email], [website], [outreach]
- For sales/copy reels: include dialogue snippets as scripts we can use
- Minimum 3, maximum 10 phrases

Rules for fact_checks:
- Only flag specific claims, stats, or recommendations that could be wrong or outdated
- "verified" = checked and accurate. "outdated" = was true but no longer. "better_alternative" = works but there's a better way now
- If no claims worth checking, return an empty array
- Maximum 3 fact checks"""

VISION_USER_ADDENDUM = """

I've also included keyframes from the video above. Read any on-screen text, URLs, tool names, repo names, stats, or visuals and incorporate them into your analysis. If the speaker references something shown on screen, identify it specifically from the frames — names, URLs, numbers, etc."""


ANALYSIS_FEEDBACK_SECTION = """

## Past Plan Feedback (use this to guide your analysis depth and focus):
{feedback_lines}

Tailor your analysis to produce insights that lead to better plans. If past feedback says tasks were too vague, provide more specific details. If plans had too many tasks, focus on fewer, higher-impact insights."""


def get_analysis_feedback_context() -> str:
    """Format recent feedback for inclusion in analysis prompts."""
    entries = get_recent_feedback(5)
    if not entries:
        return ""

    rating_labels = {"good": "GOOD", "bad": "BAD", "partial": "PARTIAL"}
    lines = []
    for entry in entries:
        label = rating_labels.get(entry["rating"], entry["rating"].upper())
        title = entry["plan_title"] or entry["reel_id"]
        comment_part = f': "{entry["comment"]}"' if entry["comment"] else ""
        lines.append(f'- Plan "{title}" was rated {label}{comment_part}')

    return "\n".join(lines)


CAROUSEL_USER_TEMPLATE = """Analyze this Instagram carousel post for actionable business insights.

**Creator:** {creator}
**Caption:** {caption}
**Slide count:** {slide_count}

**Text extracted from slides (OCR):**
{text}

Return JSON with the same schema as a reel analysis. Adapt the fields:
- video_breakdown.hook = the first slide's headline/hook
- video_breakdown.main_points = key points from each slide (in order)
- video_breakdown.key_quotes = notable text from the slides
- No duration-based info needed
- Focus on the visual content, text overlays, and educational structure

{{
  "category": "marketing|sales|ai_automation|social_media|business_ops|mindset",
  "theme": "One sentence (max 15 words) describing the core idea",
  "summary": "2-3 sentence summary of what the carousel teaches",
  "video_breakdown": {{
    "hook": "First slide headline or hook text",
    "main_points": ["Point from slide 1", "Point from slide 2", "..."],
    "key_quotes": ["Notable text from slides"],
    "creator_context": "Who this creator is and why their perspective matters"
  }},
  "detailed_notes": {{
    "what_it_is": "What this carousel is about",
    "how_useful": "How this helps Lead Needle / Free Website Wizards",
    "how_not_useful": "What doesn't apply for us",
    "target_audience": "Who on our team should see this"
  }},
  "key_insights": ["Specific actionable insight 1", "Insight 2"],
  "business_applications": [
    {{
      "area": "What area this applies to",
      "recommendation": "Specific action",
      "target_system": "ghl|n8n|sales_script|website|meta_ads|telegram|general",
      "urgency": "high|medium|low"
    }}
  ],
  "business_impact": "One sentence on bottom line impact",
  "swipe_phrases": ["Exact text from slides we can reuse"],
  "fact_checks": [],
  "routing_target": "claude-upgrades|ddb|tfww|n8n-automations|ghl-fix|aias",
  "relevance_score": 0.0-1.0
}}

Rules for routing_target — pick the SINGLE best folder for this carousel's content:
- "claude-upgrades" = AI tool improvements, Claude/LLM workflow upgrades, prompt engineering
- "ddb" = Dylan Does Business — social media content, personal brand, content creation
- "tfww" = The Free Website Wizards — sales, marketing, business ops, client acquisition, email/SMS
- "n8n-automations" = n8n workflow automations, API integrations, backend automations
- "ghl-fix" = GoHighLevel configuration, CRM setup, pipeline/funnel fixes
- "aias" = AI appointment setting — AI chatbots, conversational AI, booking flows
- If the carousel spans multiple areas, pick the PRIMARY one that best matches the core topic

Apply the same rules as reel analysis for insights, applications, and swipe phrases."""


def build_analysis_prompt(
    transcript: TranscriptResult, metadata: ReelMetadata, user_context: str = ""
) -> tuple[str, str]:
    user_prompt = USER_TEMPLATE.format(
        creator=metadata.creator or "Unknown",
        caption=metadata.caption or "No caption",
        duration=metadata.duration,
        text=transcript.text,
    )

    if user_context:
        user_prompt += f"\n\n**User notes (prioritize this direction):**\n{user_context}"

    feedback_context = get_analysis_feedback_context()
    if feedback_context:
        user_prompt += ANALYSIS_FEEDBACK_SECTION.format(
            feedback_lines=feedback_context,
        )

    return SYSTEM_PROMPT, user_prompt


def build_carousel_analysis_prompt(
    ocr_text: str,
    metadata: ReelMetadata,
    image_paths: list[Path],
    user_context: str = "",
) -> tuple[str, list]:
    """Build a multimodal prompt for carousel analysis (images + OCR text)."""
    system = SYSTEM_PROMPT + "\n\nYou are analyzing a carousel post (multiple images), not a video. There is no transcript — analyze the image content and OCR text directly."

    image_blocks = frames_to_base64(image_paths)

    text_prompt = CAROUSEL_USER_TEMPLATE.format(
        creator=metadata.creator or "Unknown",
        caption=metadata.caption or "No caption",
        slide_count=len(image_paths),
        text=ocr_text or "No text extracted from images",
    )

    if user_context:
        text_prompt += f"\n\n**User notes (prioritize this direction):**\n{user_context}"

    feedback_context = get_analysis_feedback_context()
    if feedback_context:
        text_prompt += ANALYSIS_FEEDBACK_SECTION.format(
            feedback_lines=feedback_context,
        )

    content = image_blocks + [{"type": "text", "text": text_prompt}]
    return system, content


def build_vision_analysis_prompt(
    transcript: TranscriptResult,
    metadata: ReelMetadata,
    frame_paths: list[Path],
    user_context: str = "",
) -> tuple[str, list]:
    """Build a multimodal prompt with frames + transcript for Claude vision."""
    system = SYSTEM_PROMPT + VISION_ADDENDUM

    image_blocks = frames_to_base64(frame_paths)

    text_prompt = USER_TEMPLATE.format(
        creator=metadata.creator or "Unknown",
        caption=metadata.caption or "No caption",
        duration=metadata.duration,
        text=transcript.text,
    ) + VISION_USER_ADDENDUM

    if user_context:
        text_prompt += f"\n\n**User notes (prioritize this direction):**\n{user_context}"

    feedback_context = get_analysis_feedback_context()
    if feedback_context:
        text_prompt += ANALYSIS_FEEDBACK_SECTION.format(
            feedback_lines=feedback_context,
        )

    content = image_blocks + [{"type": "text", "text": text_prompt}]
    return system, content
