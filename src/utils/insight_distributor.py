"""Distribute reel insights to relevant project folders based on topic routing.

Each project gets insights contextualized for its specific use case.
Distribution is tracked so reelbot knows where insights were sent.
"""

from datetime import datetime
from pathlib import Path

from loguru import logger

from src.utils.changes_log import log_change

PROJECTS_BASE = Path.home() / "projects" / "openclaw" / "claude-code-projects"

# Topic → which project folders get insights + sub-folder name
TOPIC_ROUTING = {
    "sales": [
        {"project": "tfww", "folder": "sales", "context": "Free website offer sales — cold outreach, objection handling, closing on video call for free website + hosting upsell"},
        {"project": "gnomeguys", "folder": "sales", "context": "In-person airport sales — selling Masters Tournament merch to private jet travelers while working as baggage assist"},
    ],
    "web_design": [
        {"project": "tfww", "folder": "web-design", "context": "Autonomous web design — CSS, layouts, UX, conversion optimization for client websites"},
    ],
    "marketing": [
        {"project": "tfww", "folder": "marketing", "context": "Lead generation and client acquisition — ads, funnels, landing pages for free website agency"},
        {"project": "gnomeguys", "folder": "marketing", "context": "Masters Tournament merch marketing — pre-orders, eBay listings, social media, Shopify"},
    ],
    "ai_automation": [
        {"project": "claude-upgrades", "folder": "reel-insights", "context": "AI tools and LLM workflow improvements"},
        {"project": "aias", "folder": "reel-insights", "context": "AI appointment setting — conversational AI, booking flows, SMS/iMessage automation"},
    ],
    "content_creation": [
        {"project": "ddb", "folder": "reel-insights", "context": "Dylan Does Business personal brand — content strategy, video production, social media growth"},
    ],
    "crm": [
        {"project": "tfww", "folder": "crm", "context": "CRM dashboard at dashboard.thefreewebsitewizards.com — pipeline, contacts, inbox, email sequences, reporting"},
    ],
    "ecommerce": [
        {"project": "gnomeguys", "folder": "reel-insights", "context": "E-commerce store (Shopify + Next.js) — product pages, cart optimization, email flows, Shopify tips, conversion optimization"},
    ],
    "appointment_setting": [
        {"project": "aias", "folder": "reel-insights", "context": "AI appointment setting via iMessage/SMS — lead qualification, booking, follow-up"},
    ],
    "funnel": [
        {"project": "tfww", "folder": "marketing", "context": "Low ticket funnel — ads → landing page → AIAS books → close on video call"},
        {"project": "aias", "folder": "reel-insights", "context": "High ticket funnel — ads → landing page → AIAS books → close on video call"},
    ],
    "sales_training": [
        {"project": "closersim", "folder": "reel-insights", "context": "AI sales call simulator — objection handling drills, closing techniques, NLP personality profiles"},
    ],
    "claude_code": [
        {"project": "claude-upgrades", "folder": "reel-insights", "context": "Claude Code improvements — new skills, prompt engineering, token optimization, MCP management"},
    ],
    "openclaw_system": [
        {"project": "claude-upgrades", "folder": "openclaw-insights", "context": "OpenClaw platform upgrades — cron jobs, Discord bot, agent config, VPS management"},
    ],
}

# Category → which topics it maps to
CATEGORY_TO_TOPICS = {
    "sales": ["sales", "funnel", "sales_training"],
    "marketing": ["marketing", "sales", "funnel", "ecommerce"],
    "ai_automation": ["ai_automation", "claude_code", "openclaw_system"],
    "social_media": ["content_creation", "marketing"],
    "business_ops": ["sales", "crm", "ecommerce"],
    "mindset": [],  # mindset rarely routes anywhere specific
    "ecommerce": ["ecommerce", "marketing"],
}

INSIGHTS_FILENAME = "reel-insights.md"
INSIGHTS_TEMPLATE = """# Reel Insights — {folder_title}

Automatically populated by ReelBot when processing Instagram reels.
Each entry is contextualized for this project's specific needs.

---

## Entries

_(New entries will be added as reels are processed)_
"""


def _ensure_folder(project: str, folder: str) -> Path:
    """Ensure the insight folder exists, creating it with a template if needed."""
    folder_path = PROJECTS_BASE / project / folder
    folder_path.mkdir(parents=True, exist_ok=True)

    insights_path = folder_path / INSIGHTS_FILENAME
    if not insights_path.exists():
        folder_title = folder.replace("-", " ").replace("/", " — ").title()
        insights_path.write_text(INSIGHTS_TEMPLATE.format(folder_title=folder_title))

    return insights_path


def _append_insights(
    path: Path,
    insights: list[str],
    reel_id: str,
    theme: str,
    creator: str,
    source_url: str,
    project_context: str,
) -> None:
    """Append insights to a reel-insights.md file."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    creator_str = f" ({creator})" if creator else ""

    entry = f"\n### {theme or reel_id} — {date_str}{creator_str}\n"
    if project_context:
        entry += f"_How this applies: {project_context}_\n\n"
    for insight in insights:
        entry += f"- {insight}\n"
    if source_url:
        entry += f"\n_Source: {source_url}_\n"

    existing = path.read_text()
    if "_(New entries will be added as reels are processed)_" in existing:
        new_content = existing.replace(
            "_(New entries will be added as reels are processed)_",
            entry.strip(),
        )
    else:
        new_content = existing.rstrip() + "\n" + entry

    path.write_text(new_content + "\n")


def _update_handoff(project: str, theme: str, folder: str) -> None:
    """Safely append a new-insights note to a project's HANDOFF.md without overwriting."""
    handoff_path = PROJECTS_BASE / project / "HANDOFF.md"
    if not handoff_path.exists():
        return

    existing = handoff_path.read_text()
    marker = "## New Reel Insights"
    date_str = datetime.now().strftime("%Y-%m-%d")
    new_line = f"- [{date_str}] **{theme}** → `{folder}/{INSIGHTS_FILENAME}`"

    if marker in existing:
        # Append to existing section (avoid duplicates)
        if new_line not in existing:
            existing = existing.replace(marker, f"{marker}\n{new_line}")
            handoff_path.write_text(existing)
    else:
        # Add new section at the end
        addition = f"\n\n{marker}\n{new_line}\n"
        handoff_path.write_text(existing.rstrip() + addition)


def distribute_insights(
    category: str,
    key_insights: list[str],
    web_design_insights: list[str],
    reel_id: str,
    theme: str = "",
    creator: str = "",
    source_url: str = "",
) -> list[dict]:
    """Distribute insights to all relevant project folders.

    Returns a list of dicts describing where insights were sent (for tracking in reelbot).
    """
    distributions = []

    # Determine which topics apply based on category
    topics = set(CATEGORY_TO_TOPICS.get(category, []))

    # Web design insights always route to web_design topic
    if web_design_insights:
        topics.add("web_design")

    # Route key_insights to all topic-matched folders
    for topic in topics:
        routes = TOPIC_ROUTING.get(topic, [])
        for route in routes:
            project = route["project"]
            folder = route["folder"]
            context = route["context"]

            # Use web_design_insights for web_design topic, key_insights for everything else
            if topic == "web_design":
                insights_to_save = web_design_insights
            else:
                insights_to_save = key_insights

            if not insights_to_save:
                continue

            try:
                path = _ensure_folder(project, folder)
                _append_insights(
                    path=path,
                    insights=insights_to_save,
                    reel_id=reel_id,
                    theme=theme,
                    creator=creator,
                    source_url=source_url,
                    project_context=context,
                )
                _update_handoff(project, theme or reel_id, folder)

                distributions.append({
                    "project": project,
                    "folder": folder,
                    "topic": topic,
                    "insight_count": len(insights_to_save),
                })
                log_change(
                    reel_id=reel_id,
                    change_type="insight_distribution",
                    target=f"{project}/{folder}",
                    summary=f"Distributed {len(insights_to_save)} {topic} insight(s) to {project}/{folder}",
                    detail="; ".join(insights_to_save[:3]),
                    source_url=source_url,
                )
                logger.info(f"Distributed {len(insights_to_save)} insights to {project}/{folder}")
            except Exception as e:
                logger.error(f"Failed to distribute to {project}/{folder}: {e}")

    return distributions
