from src.models import AnalysisResult, ReelMetadata
from src.utils.feedback import get_recent_feedback
from src.utils.shared_context import build_business_context

SYSTEM_PROMPT_TEMPLATE = """You are an implementation planner for Lead Needle LLC.

BUSINESS CONTEXT — LIVE PROJECT DATA (auto-generated from project status files):
{business_context}

OUR PRICING MODEL: AIAS is $5,000 setup + $300/month + $10 per qualified booked appointment. TFWW websites are free (revenue from hosting affiliates). Both are sold on sales calls using the same call flow. Sales insights from reels often apply to BOTH products. Recommendations about close rates, pricing, or conversion optimization help clients succeed = retention.

CRITICAL RULES:

1. GENERATE 3 IMPLEMENTATION LEVELS — every plan has 3 tiers:
   - Level 1 "Note it": Just record the insight. Add a note, bookmark, or doc entry. (0.25h max)
   - Level 2 "Build it": One practical implementation task. Build/tweak something specific. (0.5-2h)
   - Level 3 "Go deep": ONE ambitious extension. NOT a wishlist — one concrete next step after L2 proves value. (1-3h, EXACTLY 1 task)

2. MOST REELS ARE SMALL. Not every video is revolutionary. Default to lean plans:
   - A sales technique reel → L1 note + L2 script/prompt tweak. That's it.
   - A tool demo → L1 note + L2 install/configure it.
   - Only generate a substantive L3 if there's a genuinely valuable extension that's grounded in current systems.
   - If L3 would just be "build infrastructure to support L2" (A/B testing, classification pipelines, dashboards, CRM fields), SKIP IT. Just add a simpler L3 like "apply same technique to second system" or a content task.

3. NO SPECULATIVE INFRASTRUCTURE. Do NOT propose:
   - A/B testing frameworks that don't exist
   - Classification pipelines for things not yet proven
   - Dashboard widgets for metrics not yet tracked
   - Database schema changes for features not yet validated
   These are premature. The user will build infrastructure AFTER a technique proves valuable, not before.

4. ONE AIAS CHANGE PER PLAN. If the reel inspires an AIAS prompt change AND a sales script change, pick the STRONGER one for L2. The other goes in L1 notes or L3. Don't generate conflicting rewrites across plans.

5. BE CONCISE. Level summaries should be 1 sentence. Task descriptions should be specific but not padded.

6. DON'T REINVENT WHAT EXISTS. Check the project data above — if a system already works, extend it, don't rebuild it.

7. SCOPE TO SPECIFIC PROJECTS. Each task should name which project it applies to (reelbot, aias, tfww, ddb, ghl-fix, n8n-automations).

8. CONTENT ANGLE: If the reel could inspire a DDB (Dylan Does Business) video or post, include a one-line content_angle. If not relevant, leave it empty.

9. TOTAL PLAN HOURS: L1+L2+L3 combined should rarely exceed 4h. If you're over 4h, you're over-engineering.

Available tools: Claude Code, Meta Ads, Website (thefreewebsitewizards.com), Telegram bot, sales_script API, knowledge_base

WEB DESIGN TASKS: Reference tfww/web-design/ knowledge base, use our Tailwind v4 + static HTML stack, include specific CSS/classes.

Respond with valid JSON only."""


def _get_system_prompt() -> str:
    """Build system prompt with live business context."""
    context = build_business_context()
    if not context:
        context = "(No shared context files found — check ~/projects/openclaw/.shared-context/)"
    return SYSTEM_PROMPT_TEMPLATE.format(business_context=context)

USER_TEMPLATE = """Convert this reel analysis into a tiered implementation plan.

**Source Reel:** {url} (by {creator})
**Category:** {category}
**Theme:** {theme}
**Summary:** {summary}
**Business Impact:** {business_impact}
**Relevance:** {relevance_score}

**Key Insights:**
{insights_formatted}

**Business Applications:**
{applications_formatted}

**Reality Checks:**
{reality_checks_formatted}

Return JSON:
{{
  "title": "Concise plan title (max 8 words)",
  "summary": "1 sentence — what this plan achieves",
  "recommended_action": "1 sentence — the single most impactful thing Dylan should do based on this reel. Be specific and direct, e.g. 'Add objection handler X to AIAS sales flow' not 'Consider implementing improvements'",
  "content_angle": "DDB content idea if relevant, or empty string",
  "level_summaries": {{
    "1": "What level 1 does (1 sentence)",
    "2": "What level 2 does (1 sentence)",
    "3": "What level 3 does (1 sentence)"
  }},
  "tasks": [
    {{
      "title": "Task title (imperative verb)",
      "description": "What to do. For copy, include EXACT text. Be specific, not padded.",
      "level": 1,
      "priority": "high|medium|low",
      "estimated_hours": 0.25,
      "deliverables": ["Concrete output"],
      "tools": ["sales_script"],
      "requires_human": false,
      "human_reason": "",
      "tool_data": {{}},
      "change_type": "addition|replacement|reinforcement|ignore"
    }}
  ]
}}

Level rules:
- Level 1: EXACTLY 1 task. A note, bookmark, or doc entry. Max 0.25h.
- Level 2: EXACTLY 1 task. A practical build/tweak. 0.5-2h.
- Level 3: EXACTLY 1 task. One concrete extension of L2 — NOT infrastructure or A/B tests. Max 3h.
- Levels are cumulative — approving L2 also executes L1, approving L3 executes all.
- Every level MUST have exactly 1 task. Total tasks: 3.
- TOTAL PLAN: 3 tasks, under 4h combined. Lean is better.

Rules for tool_data — CRITICAL for automated execution:
- WITHOUT tool_data, tasks just get logged and nothing happens
- For "sales_script" tasks — two modes:
  - FULL REWRITE: {{"section_id": "<valid_id>", "new_content": "The COMPLETE replacement text"}}
  - ADD A NOTE: {{"section_id": "<valid_id>", "note": "Brief guidance"}}
  - section_id MUST match a valid ID from the script sections listed below
- For "content" tasks: {{"content_type": "ad_copy|email|social_post", "drafts": ["Complete draft..."]}}
- For "claude_code" tasks: {{"files_to_modify": ["path/to/file.py"], "change_description": "..."}}
- For "website" tasks: {{"page": "homepage|about|pricing", "changes": ["..."]}}
- For "knowledge_base" tasks (PREFERRED for L1): {{"title": "Short insight title", "content": "The insight or note to save", "category": "ai_automation|sales|marketing|operations|product", "tags": ["tag1", "tag2"]}}
- Every task MUST have populated tool_data
- L1 tasks should ALWAYS use "knowledge_base" tool unless they specifically modify an existing system"""

EXISTING_PLANS_SECTION = """

**Existing plans (avoid duplicating these tasks):**
{existing_plans}"""

CAPABILITIES_SECTION = """

**Existing Capabilities (DO NOT rebuild — extend for new use cases):**
{capabilities}"""

KB_CONTEXT_SECTION = """

**Recent Knowledge Base entries (avoid duplicating these insights):**
{kb_context}"""

COMPARISON_SECTION = """

**Comparison to Existing Plans (use this to set change_type on tasks):**
{comparison_context}

When you see a comparison:
- verdict "better" → task change_type should be "replacement"
- verdict "different_angle" → task change_type should be "addition"
- verdict "same" → task change_type should be "reinforcement" (or skip the task)
- verdict "worse" → task change_type should be "ignore" (don't create a task for it)"""

FEEDBACK_SECTION = """

## Past Feedback (learn from these):
{feedback_lines}

Use this feedback to improve the quality of your plan. Repeat what worked, avoid what didn't."""


def get_feedback_context() -> str:
    """Format recent feedback entries for inclusion in prompts."""
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


SCRIPT_CONTEXT_SECTION = """

**Current Sales Script (modify sections via API):**
{script_content}

**Valid section IDs for PUT /api/script/sections/{{id}}:**
{section_ids}

When tasks involve script changes:
- Reference the EXACT section ID (e.g., "price_objection")
- Show the current text AND the replacement text
- Use tool "sales_script" with the section ID for script edit tasks"""


def build_plan_prompt(
    analysis: AnalysisResult, metadata: ReelMetadata,
    existing_plans_summary: str = "",
    script_context: str = "",
    script_section_ids: str = "",
    capabilities_context: str = "",
    user_context: str = "",
    comparison_context: str = "",
) -> tuple[str, str]:
    insights_formatted = "\n".join(f"- {i}" for i in analysis.key_insights)

    applications_formatted = "- None identified"
    if analysis.business_applications:
        applications_formatted = "\n".join(
            f"- [{ba.urgency.upper()}] {ba.area}: {ba.recommendation} (target: {ba.target_system})"
            for ba in analysis.business_applications
        )

    reality_checks_formatted = "- No claims flagged"
    if analysis.reality_checks:
        reality_checks_formatted = "\n".join(
            f"- [{rc.verdict}] \"{rc.claim}\" — {rc.explanation}"
            + (f" Better: {rc.better_alternative}" if rc.better_alternative else "")
            for rc in analysis.reality_checks
        )

    user_prompt = USER_TEMPLATE.format(
        url=metadata.url,
        creator=metadata.creator or "Unknown",
        category=analysis.category,
        theme=analysis.theme or "Not specified",
        summary=analysis.summary,
        business_impact=analysis.business_impact or "Not assessed",
        relevance_score=analysis.relevance_score,
        insights_formatted=insights_formatted,
        applications_formatted=applications_formatted,
        reality_checks_formatted=reality_checks_formatted,
    )

    if capabilities_context:
        user_prompt += CAPABILITIES_SECTION.format(
            capabilities=capabilities_context,
        )

    if existing_plans_summary:
        user_prompt += EXISTING_PLANS_SECTION.format(
            existing_plans=existing_plans_summary,
        )

    if script_context:
        user_prompt += SCRIPT_CONTEXT_SECTION.format(
            script_content=script_context,
            section_ids=script_section_ids,
        )

    # Inject recent knowledge base entries to avoid duplicate insights
    from src.utils.knowledge_base import get_recent_context
    kb_context = get_recent_context(limit=10)
    if kb_context:
        user_prompt += KB_CONTEXT_SECTION.format(kb_context=kb_context)

    if comparison_context:
        user_prompt += COMPARISON_SECTION.format(comparison_context=comparison_context)

    if user_context:
        user_prompt += f"\n\n**User notes (prioritize this direction):**\n{user_context}"

    feedback_context = get_feedback_context()
    if feedback_context:
        user_prompt += FEEDBACK_SECTION.format(feedback_lines=feedback_context)

    return _get_system_prompt(), user_prompt
