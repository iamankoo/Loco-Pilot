"""Default "LocoPilot Storage" workspace provisioning.

Used whenever a caller (execution creation, project creation) doesn't
supply an explicit workspace_path — instead of rejecting the request, a
project directory is created under the configured LocoPilot Storage root
(`Settings.workspace_root`), never inside the repository itself and never
a hardcoded personal path.
"""

from __future__ import annotations

import re
import uuid

from backend.app.core.config import get_settings


def slugify(text: str, *, max_length: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug[:max_length].rstrip("-")) or "project"


def provision_default_workspace(*, seed_text: str, project_name: str | None) -> tuple[str, str]:
    """Creates `<workspace_root>/projects/<slug>` and returns (name, path)."""
    base_slug = slugify(project_name or seed_text)
    slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"
    project_dir = get_settings().workspace_root / "projects" / slug
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_name or base_slug, str(project_dir)
