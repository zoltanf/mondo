"""XDG-compliant cache directory resolution.

Resolution order for the cache root:
    1. Explicit `override` argument
    2. `MONDO_CACHE_DIR` env var
    3. `$XDG_CACHE_HOME/mondo/<profile>/`
    4. `$HOME/.cache/mondo/<profile>/`
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_PROFILE_NAME = "default"


def cache_dir(profile: str | None = None, *, override: str | Path | None = None) -> Path:
    """Return the resolved cache directory path (does not create it).

    `profile` is the caller's effective profile name (e.g. the one used to
    resolve the API token). Subdirectories are used per profile so different
    monday accounts don't collide.
    """
    if override is not None:
        return Path(override)

    env_override = os.environ.get("MONDO_CACHE_DIR")
    if env_override:
        return Path(env_override) / (profile or DEFAULT_PROFILE_NAME)

    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "mondo" / (profile or DEFAULT_PROFILE_NAME)
