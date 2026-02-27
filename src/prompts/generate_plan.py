from src.models import AnalysisResult, ReelMetadata

SYSTEM_PROMPT = """You are an implementation planner for Lead Needle LLC / The Free Website Wizards.

You convert business insights into concrete, executable tasks. Each task must be specific enough for an AI agent (Claude Code) or a team member to complete without ambiguity.

CRITICAL RULE: When the reel teaches a language technique, copywriting framework, or messaging approach — the plan MUST include tasks that directly USE that language. Don't just say "update copy." Write out the EXACT new copy, phrases, subject lines, or ad text as part of the task description. The deliverables should include draft copy ready to deploy.

For example, if the reel teaches "on us" reframing:
- BAD task: "Update website to use gift-framing language"
- GOOD task: "Replace 'Free website audit' → 'Your website audit is on us' on homepage hero. Replace 'Free AI chatbot' → 'AI chatbot setup is on us' on services page. Replace 'Free consultation' → 'Your strategy call is on us' on booking page."

Available tools and platforms:
- n8n (self-hosted at n8n.leadneedleai.com) — workflow automation
- GoHighLevel (GHL) — CRM, pipelines, calendars, campaigns, email/SMS sequences
- Claude Code — code generation, content creation, automation scripts
- Meta Ads — Facebook/Instagram advertising
- Website — thefreewebsitewizards.com
- Telegram bot — notifications and triggers

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
      "description": "Exactly what to do, step by step. Include SPECIFIC copy, phrases, or text to use — not just instructions to 'update copy'. Write the actual words.",
      "priority": "high|medium|low",
      "estimated_hours": 1.0,
      "deliverables": ["Concrete output 1 — include draft copy where applicable"],
      "dependencies": ["Other task title if needed"],
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
- Incorporate the swipe phrases directly into task descriptions and deliverables"""


def build_plan_prompt(
    analysis: AnalysisResult, metadata: ReelMetadata
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
    return SYSTEM_PROMPT, user_prompt
