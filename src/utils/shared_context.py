"""Load shared project context for dynamic prompt injection.

Checks two locations:
1. ~/projects/openclaw/.shared-context/ (local dev, updated by project sessions)
2. /app/shared-context/ or ./shared-context/ (bundled in Docker image for production)
"""

from pathlib import Path

# Local dev path (updated live by project sessions)
_LOCAL_DIR = Path.home() / "projects" / "openclaw" / ".shared-context"
# Bundled path (baked into Docker image at build time)
_BUNDLED_DIR = Path("/app/shared-context")
# Repo-relative fallback
_REPO_DIR = Path(__file__).resolve().parent.parent.parent / "shared-context"


def _get_context_dir() -> Path | None:
    """Return the first available shared context directory."""
    for d in (_LOCAL_DIR, _BUNDLED_DIR, _REPO_DIR):
        if d.exists() and any(d.glob("*.md")):
            return d
    return None


SHARED_CONTEXT_DIR = _get_context_dir() or _LOCAL_DIR  # resolved at import time

# Map routing targets to context file names
ROUTING_TO_CONTEXT = {
    "claude-upgrades": [],
    "ddb": ["ddb.md"],
    "tfww": ["tfww.md"],
    "n8n-automations": [],
    "ghl-fix": [],
    "aias": ["aias.md"],
}


def load_all_context() -> str:
    """Load all shared project context files into a single string for prompts."""
    if not SHARED_CONTEXT_DIR.exists():
        return ""

    sections = []
    for md_file in sorted(SHARED_CONTEXT_DIR.glob("*.md")):
        content = md_file.read_text().strip()
        if content:
            sections.append(content)

    return "\n\n---\n\n".join(sections)


def load_context_for_routing(routing_target: str) -> str:
    """Load context files relevant to a specific routing target."""
    if not SHARED_CONTEXT_DIR.exists():
        return ""

    files = ROUTING_TO_CONTEXT.get(routing_target, [])
    if not files:
        return ""

    sections = []
    for fname in files:
        path = SHARED_CONTEXT_DIR / fname
        if path.exists():
            content = path.read_text().strip()
            if content:
                sections.append(content)

    return "\n\n".join(sections)


def build_business_context() -> str:
    """Build the business context string for prompts from shared context files.

    Returns a formatted string summarizing all projects, suitable for injection
    into analysis and planning prompts.
    """
    if not SHARED_CONTEXT_DIR.exists():
        return ""

    sections = []
    for md_file in sorted(SHARED_CONTEXT_DIR.glob("*.md")):
        content = md_file.read_text().strip()
        if not content:
            continue

        # Extract the first heading and "What It Does" + "Capabilities" + "Current Status"
        lines = content.split("\n")
        name = lines[0].lstrip("# ").split("—")[0].strip() if lines else md_file.stem

        what_it_does = _extract_section(content, "What It Does")
        capabilities = _extract_section(content, "Capabilities")
        status = _extract_section(content, "Current Status")
        stack = _extract_section(content, "Stack")

        summary = f"**{name}**"
        if what_it_does:
            summary += f"\n  Purpose: {what_it_does}"
        if stack:
            summary += f"\n  Stack: {stack}"
        if capabilities:
            summary += f"\n  Can do: {capabilities}"
        if status:
            summary += f"\n  Status: {status}"

        sections.append(summary)

    return "\n\n".join(sections)


def _extract_section(content: str, heading: str) -> str:
    """Extract the content under a ## heading, returning it as a compact string."""
    lines = content.split("\n")
    capture = False
    result = []

    for line in lines:
        if line.strip().startswith("## ") and heading.lower() in line.lower():
            capture = True
            continue
        elif line.strip().startswith("## ") and capture:
            break
        elif capture:
            stripped = line.strip()
            if stripped and not stripped.startswith("```"):
                # Compact bullet points
                if stripped.startswith("- **"):
                    # Extract key: value from "- **Key**: Value"
                    result.append(stripped.lstrip("- "))
                elif stripped.startswith("- "):
                    result.append(stripped[2:])
                else:
                    result.append(stripped)

    return "; ".join(result) if result else ""
