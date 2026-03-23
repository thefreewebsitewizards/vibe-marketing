from pathlib import Path

from src.models import TranscriptResult, ReelMetadata
from src.services.frames import frames_to_base64
from src.utils.feedback import get_recent_feedback
from src.utils.shared_context import build_business_context

SYSTEM_PROMPT_TEMPLATE = """You are a technical analyst for Lead Needle LLC.

BUSINESS CONTEXT — LIVE PROJECT DATA (auto-generated from project status files):
{business_context}

YOUR JOB: Extract PRACTICAL insights from Instagram Reels. Focus on:
- What's the actual tool/technique shown?
- Can we use it? If so, HOW specifically?
- What claims does the creator make? Are they accurate?
- DON'T take the creator's word as gospel — verify claims, note limitations

CRITICAL RULES:
- If the video is about a TECH TOOL or UPDATE: focus on setup steps and practical usage. Do NOT generate sales copy or website rewrites from tech videos.
- If the video is about MARKETING/SALES: then swipe phrases and copy are appropriate.
- Match your output to the video type. A tech demo → tech implementation. A sales technique → sales insights.
- Be SKEPTICAL of creator claims. Reality-check bold statements. Note if the creator is selling a course or has a financial incentive.
- When audience comments are provided, use them as signal — do commenters confirm the advice works? Push back? Share caveats? This is real-world validation.
- Keep analysis concise. No padding, no redundancy.
- Reference EXISTING capabilities from the project data above. Don't suggest rebuilding what already works.
- MATCH DEPTH TO COMPLEXITY. A simple "use this tool/skill" video needs a short analysis. A complex strategy video deserves more depth. Don't over-analyze simple content.

Respond with valid JSON only. No markdown, no explanation outside the JSON."""


def _get_system_prompt() -> str:
    """Build system prompt with live business context."""
    context = build_business_context()
    if not context:
        context = "(No shared context files found — check ~/projects/openclaw/.shared-context/)"
    return SYSTEM_PROMPT_TEMPLATE.format(business_context=context)

VISION_ADDENDUM = """

IMPORTANT — VIDEO FRAMES PROVIDED: You are also given keyframes from the video. The speaker may reference things shown on screen (URLs, repo names, tool names, screenshots, stats, text overlays) that are NOT in the transcript. READ the frames carefully and include any on-screen text, links, tool names, or data in your analysis. If the speaker says "look at this" or "this right here," the frames show what they're pointing at."""

USER_TEMPLATE = """Analyze this Instagram Reel transcript for actionable business insights.

**Creator:** {creator}
**Caption:** {caption}
**Duration:** {duration:.0f}s
**Posted:** {upload_date}
**Engagement:** {like_count} likes, {comment_count} comments
{comments_section}
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
      "target_system": "sales_script|website|meta_ads|telegram|general",
      "urgency": "high|medium|low"
    }}
  ],
  "business_impact": "One sentence on how this affects our bottom line if implemented",
  "swipe_phrases": [
    "Exact phrase or adapted version we can use in our copy"
  ],
  "reality_checks": [
    {{
      "claim": "A specific claim, strategy, or recommendation from the reel",
      "verdict": "solid|plausible|questionable|misleading",
      "explanation": "Why this verdict — reference audience comments if they confirm or contradict",
      "better_alternative": "If questionable or misleading, what to do instead"
    }}
  ],
  "routing_target": "claude-upgrades|ddb|tfww|aias|gnomeguys|closersim",
  "relevance_score": 0.0-1.0,
  "web_design_insights": [
    "Specific web design tip, technique, or principle from this reel (if any)",
    "CSS trick, layout pattern, UX principle, conversion optimization, etc."
  ],
  "content_response": {{
    "react_angle": "How to respond/react to build authority — frame as 'We should...' or 'Our take...'",
    "corrections": ["Things the video got wrong we can correct publicly — only include if genuinely wrong"],
    "repurpose_ideas": ["How to take this content for our channels — specific format + platform"],
    "engagement_hook": "Suggested comment or reply to the original post — natural, not salesy"
  }}
}}

Rules for relevance_score — CALIBRATION GUIDE (the user pre-filters reels, so most will be relevant):
- 0.95-1.0 = Directly actionable TODAY with our exact stack/clients. Clear ROI, specific tools we already use
- 0.90-0.94 = Highly relevant strategy or technique we should implement this week
- 0.85-0.89 = Useful with some adaptation — good idea but needs tweaking for our context
- 0.80-0.84 = Tangentially relevant — interesting but lower priority, might be useful later
- Below 0.80 = Only use this for genuinely off-topic content (rare since user pre-filters)
- Default expectation: most reels should score 0.85-0.95. Scoring below 0.80 means the content has almost nothing to do with our business
- DO NOT give low scores just because the advice is "common" or "basic" — if it applies to us and is actionable, score it high

Rules for routing_target — pick the SINGLE best folder for this reel's content:
- "claude-upgrades" = AI tool improvements, Claude/LLM workflow upgrades, prompt engineering
- "ddb" = Dylan Does Business — social media content, personal brand, content creation
- "tfww" = The Free Website Wizards — sales, marketing, CRM, funnels, client acquisition, email/SMS
- "aias" = AI appointment setting — AI chatbots, conversational AI, booking flows, high ticket funnel
- "gnomeguys" = E-commerce — Shopify, product pages, cart optimization, email flows, conversion
- "closersim" = Sales training — closing techniques, objection handling drills, sales psychology
- If the reel spans multiple areas, pick the PRIMARY one that best matches the core topic
- If nothing fits well, pick the closest match — the insight distributor handles cross-routing

Rules for web_design_insights:
- Extract ANY web design knowledge: CSS techniques, layout strategies, typography tips, color theory, UX patterns, conversion optimization, responsive design, animation techniques, accessibility, performance, design tools
- Include specifics: exact CSS properties, pixel values, font pairings, color codes, breakpoints, tool names
- If the reel has NOTHING to do with web design, return an EMPTY array
- These insights feed directly into our autonomous web design knowledge base
- Frame as actionable techniques, not vague advice (e.g. "Use 16px minimum body text for readability" not "make text readable")
- Maximum 10 insights per reel

Rules for content_response:
- react_angle: How we'd publicly respond to this content. Frame as authority building, not criticism
- corrections: Only include if the creator made factually wrong claims. Empty array if nothing wrong
- repurpose_ideas: Specific format (carousel, reel, newsletter) + which platform. Max 3
- engagement_hook: A natural-sounding comment we could leave on the original post. Skip if no good angle

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

Rules for business_applications — THINK IN LAYERS:
- Each must name a specific target_system we'd implement it in
- urgency "high" = do this week, "medium" = this month, "low" = backlog
- Think at 3 depths:
  1. OUR OPS: How does this improve our internal operations? (sales process, close rates, efficiency)
  2. OUR CLIENTS: How does this help our clients succeed? (they pay for booked appointments, not closes — so helping them close better = retention)
  3. OUR PRODUCT: Could this become a feature in the AIAS app dashboard? (e.g., close rate tracking, pricing recommendations, performance insights)
- Minimum 1, maximum 5 applications

Rules for swipe_phrases:
- ONLY include swipe phrases if the video is about marketing, sales, or copywriting
- For tech/automation videos: return an EMPTY array — no swipe phrases
- Pull EXACT powerful phrases from the transcript, label with [ad], [email], [website], [outreach]
- Maximum 5 phrases

Rules for reality_checks — this is NOT literal fact-checking, it's "is this actually a good idea for us?":
- Evaluate the core advice/strategy: is it solid, plausible, questionable, or misleading?
- "solid" = proven approach, audience confirms it works, aligns with our experience
- "plausible" = sounds right but unproven or context-dependent
- "questionable" = oversimplified, missing important caveats, or audience pushes back
- "misleading" = actively bad advice, creator has financial incentive to mislead, or comments call BS
- USE AUDIENCE COMMENTS as evidence. If commenters share success stories → solid. If they push back → questionable
- If the creator is selling a course/product related to the advice, note that bias
- RECENCY MATTERS: Check the post date and consider how fast this particular space moves. AI tooling changes weekly — a video recommending a specific model or API from months ago may already be superseded. Sales principles tend to be more evergreen. Use your judgment based on the actual content. If the video recommends a specific tool, API, model, or platform, consider whether something better has emerged since the post date
- If no claims worth checking, return an empty array
- Maximum 3 reality checks"""

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
      "target_system": "sales_script|website|meta_ads|telegram|general",
      "urgency": "high|medium|low"
    }}
  ],
  "business_impact": "One sentence on bottom line impact",
  "swipe_phrases": ["Exact text from slides we can reuse"],
  "reality_checks": [],
  "routing_target": "claude-upgrades|ddb|tfww|aias|gnomeguys|closersim",
  "relevance_score": 0.0-1.0,
  "web_design_insights": [
    "Specific web design tip or technique from this carousel (if any)"
  ],
  "content_response": {{
    "react_angle": "How to respond/react to build authority — frame as 'We should...' or 'Our take...'",
    "corrections": ["Things the carousel got wrong we can correct publicly — only include if genuinely wrong"],
    "repurpose_ideas": ["How to take this content for our channels — specific format + platform"],
    "engagement_hook": "Suggested comment or reply to the original post — natural, not salesy"
  }}
}}

Rules for routing_target — pick the SINGLE best folder for this carousel's content:
- "claude-upgrades" = AI tool improvements, Claude/LLM workflow upgrades, prompt engineering
- "ddb" = Dylan Does Business — social media content, personal brand, content creation
- "tfww" = The Free Website Wizards — sales, marketing, CRM, funnels, client acquisition, email/SMS
- "aias" = AI appointment setting — AI chatbots, conversational AI, booking flows, high ticket funnel
- "gnomeguys" = E-commerce — Shopify, product pages, cart optimization, email flows, conversion
- "closersim" = Sales training — closing techniques, objection handling drills, sales psychology
- If the carousel spans multiple areas, pick the PRIMARY one that best matches the core topic

Apply the same rules as reel analysis for insights, applications, swipe phrases, and relevance_score calibration (most should be 0.85-0.95)."""


def _format_comments(metadata: ReelMetadata) -> str:
    """Format top comments for inclusion in the prompt."""
    if not metadata.comments:
        return ""
    lines = ["**Top Comments:**"]
    for c in metadata.comments[:5]:
        author = c.get("author", "?")
        text = c.get("text", "").replace("\n", " ").strip()
        if text:
            lines.append(f'- @{author}: "{text}"')
    return "\n".join(lines) + "\n"


def build_analysis_prompt(
    transcript: TranscriptResult, metadata: ReelMetadata, user_context: str = ""
) -> tuple[str, str]:
    user_prompt = USER_TEMPLATE.format(
        creator=metadata.creator or "Unknown",
        caption=metadata.caption or "No caption",
        duration=metadata.duration,
        upload_date=metadata.upload_date or "Unknown",
        like_count=metadata.like_count,
        comment_count=metadata.comment_count,
        comments_section=_format_comments(metadata),
        text=transcript.text,
    )

    if user_context:
        user_prompt += f"\n\n**User notes (prioritize this direction):**\n{user_context}"

    feedback_context = get_analysis_feedback_context()
    if feedback_context:
        user_prompt += ANALYSIS_FEEDBACK_SECTION.format(
            feedback_lines=feedback_context,
        )

    return _get_system_prompt(), user_prompt


def build_carousel_analysis_prompt(
    ocr_text: str,
    metadata: ReelMetadata,
    image_paths: list[Path],
    user_context: str = "",
) -> tuple[str, list]:
    """Build a multimodal prompt for carousel analysis (images + OCR text)."""
    system = _get_system_prompt() + "\n\nYou are analyzing a carousel post (multiple images), not a video. There is no transcript — analyze the image content and OCR text directly."

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
    system = _get_system_prompt() + VISION_ADDENDUM

    image_blocks = frames_to_base64(frame_paths)

    text_prompt = USER_TEMPLATE.format(
        creator=metadata.creator or "Unknown",
        caption=metadata.caption or "No caption",
        duration=metadata.duration,
        upload_date=metadata.upload_date or "Unknown",
        like_count=metadata.like_count,
        comment_count=metadata.comment_count,
        comments_section=_format_comments(metadata),
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
