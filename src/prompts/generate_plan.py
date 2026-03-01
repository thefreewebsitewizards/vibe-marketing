from src.models import AnalysisResult, ReelMetadata

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
**Summary:** {summary}
**Relevance:** {relevance_score}

**Key Insights:**
{insights_formatted}

**Swipe Phrases (ready-to-use copy from the reel):**
{phrases_formatted}

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
      "tools": ["n8n", "ghl", "claude_code", "meta_ads", "website"]
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
- Do NOT duplicate tasks that already exist in previous plans (see existing plans below)"""

EXISTING_PLANS_SECTION = """

**Existing plans (avoid duplicating these tasks):**
{existing_plans}"""

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
) -> tuple[str, str]:
    insights_formatted = "\n".join(f"- {i}" for i in analysis.key_insights)
    phrases_formatted = "\n".join(f"- {p}" for p in analysis.swipe_phrases) if analysis.swipe_phrases else "- None extracted"

    user_prompt = USER_TEMPLATE.format(
        url=metadata.url,
        creator=metadata.creator or "Unknown",
        category=analysis.category,
        summary=analysis.summary,
        relevance_score=analysis.relevance_score,
        insights_formatted=insights_formatted,
        phrases_formatted=phrases_formatted,
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

    return SYSTEM_PROMPT, user_prompt
