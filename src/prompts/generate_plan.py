from src.models import AnalysisResult, ReelMetadata
from src.utils.feedback import get_recent_feedback

SYSTEM_PROMPT = """You are an implementation planner for Lead Needle LLC / The Free Website Wizards.

You convert business insights into concrete, executable tasks. Each task must be specific enough for an AI agent (Claude Code) or a team member to complete without ambiguity.

CRITICAL RULES:

1. SHOW THE ACTUAL COPY. When a task involves copy/messaging, include the exact text to use:
   - BAD: "Update website to use gift-framing language"
   - GOOD: "Homepage hero: 'Your website is on us — we build it, you grow.' Services page CTA: 'Your strategy call is on us.' Replace all 'Free X' with 'X is on us.'"

2. TECHNICAL FEASIBILITY. Only assign tasks that the listed tools can actually do:
   - Claude Code: Write text, code, configs, API calls. CANNOT generate images or edit video.
   - n8n: Workflow automation between APIs. NOT a data source itself.
   - GHL: CRM, email/SMS sequences, forms, pipelines. NOT an ad creative tool.
   - Meta Ads: Campaign management, audience targeting, ad copy. Image/video creative needs separate tools.
   - If a task needs something our tools can't do, say so and suggest the right tool.

3. VALIDATE DEPENDENCIES. If Task B depends on Task A, Task B's description must reference what specific output from Task A it uses.

4. DON'T ASSUME DATA EXISTS. If a task requires external data (client metrics, industry stats), the plan must include a task to gather that data first. Don't invent statistics.

Available tools and platforms:
- n8n (self-hosted at n8n.leadneedleai.com) — workflow automation
- GoHighLevel (GHL) — CRM, pipelines, calendars, campaigns, email/SMS sequences
- Claude Code — code generation, content creation, automation scripts
- Meta Ads — Facebook/Instagram advertising
- Website — thefreewebsitewizards.com
- Telegram bot — notifications and triggers
- sales_script — edit specific sections of Dylan's sales call script via PUT /api/script/sections/{section_id}

Respond with valid JSON only. No markdown, no explanation outside the JSON."""

USER_TEMPLATE = """Convert this reel analysis into an implementation plan.

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

**Swipe Phrases (ready-to-use copy from the reel):**
{phrases_formatted}

**Fact Checks:**
{fact_checks_formatted}

Return JSON:
{{
  "title": "Concise plan title",
  "summary": "What this plan achieves in 2-3 sentences",
  "tasks": [
    {{
      "title": "Task title (imperative verb)",
      "description": "Step by step what to do. For copy tasks, include the EXACT text to use — headlines, email subject lines, CTAs, scripts. Don't just describe the approach, write the actual words.",
      "priority": "high|medium|low",
      "estimated_hours": 1.0,
      "deliverables": ["Concrete output — for copy deliverables, include the draft text"],
      "dependencies": ["Other task title if needed — state what output is used"],
      "tools": ["n8n", "ghl", "claude_code", "meta_ads", "website"],
      "requires_human": false,
      "human_reason": ""
    }}
  ]
}}

Rules:
- Order tasks by priority (high first) then by dependency
- Each task must have at least one deliverable
- Estimated hours should be realistic (0.5 - 8 hours per task)
- Maximum 7 tasks per plan
- Every task must use at least one of our available tools
- Tasks that involve copy/messaging MUST include the actual draft text, not just "write copy"
- Incorporate the swipe phrases directly into task descriptions and deliverables
- If a task requires data we don't have yet, create a preceding task to gather it
- Do NOT duplicate tasks that already exist in previous plans (see existing plans below)
- Set requires_human=true for tasks that need human judgment (ad spend, client outreach, content approval). Explain why in human_reason
- If a fact check flagged something as "outdated" or "better_alternative", account for the correction in your tasks"""

EXISTING_PLANS_SECTION = """

**Existing plans (avoid duplicating these tasks):**
{existing_plans}"""

CAPABILITIES_SECTION = """

**Existing Capabilities (DO NOT suggest rebuilding these — reference them for new use cases instead):**
{capabilities}"""

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
) -> tuple[str, str]:
    insights_formatted = "\n".join(f"- {i}" for i in analysis.key_insights)
    phrases_formatted = "\n".join(f"- {p}" for p in analysis.swipe_phrases) if analysis.swipe_phrases else "- None extracted"

    applications_formatted = "- None identified"
    if analysis.business_applications:
        applications_formatted = "\n".join(
            f"- [{ba.urgency.upper()}] {ba.area}: {ba.recommendation} (target: {ba.target_system})"
            for ba in analysis.business_applications
        )

    fact_checks_formatted = "- No claims flagged"
    if analysis.fact_checks:
        fact_checks_formatted = "\n".join(
            f"- [{fc.verdict}] \"{fc.claim}\" — {fc.explanation}"
            + (f" Better: {fc.better_alternative}" if fc.better_alternative else "")
            for fc in analysis.fact_checks
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
        phrases_formatted=phrases_formatted,
        fact_checks_formatted=fact_checks_formatted,
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

    if user_context:
        user_prompt += f"\n\n**User notes (prioritize this direction):**\n{user_context}"

    feedback_context = get_feedback_context()
    if feedback_context:
        user_prompt += FEEDBACK_SECTION.format(feedback_lines=feedback_context)

    return SYSTEM_PROMPT, user_prompt
