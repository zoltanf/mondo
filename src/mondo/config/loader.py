"""XDG-compliant config loader with env-var expansion.

Resolution order:
    1. Explicit `path` argument (for tests / `--config` flag later)
    2. `MONDO_CONFIG` env var
    3. `$XDG_CONFIG_HOME/mondo/config.yaml`
    4. `$HOME/.config/mondo/config.yaml`
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from mondo.config.schema import Config

DEFAULT_API_URL = "https://api.monday.com/v2"
DEFAULT_API_VERSION = "2026-01"

_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigFileNotFoundError(FileNotFoundError):
    """Raised by load_config(strict=True) when the config file is absent."""


def config_path() -> Path:
    """Return the resolved config file path (does not check existence)."""
    override = os.environ.get("MONDO_CONFIG")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "mondo" / "config.yaml"


def _expand_env_vars(data: Any) -> Any:
    """Recursively expand ${VAR} tokens in string values. Unresolved vars are
    left as literals so the user can see what's missing."""
    if isinstance(data, str):

        def repl(m: re.Match[str]) -> str:
            var = m.group(1)
            return os.environ.get(var, m.group(0))

        return _ENV_VAR_RE.sub(repl, data)
    if isinstance(data, dict):
        return {k: _expand_env_vars(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_expand_env_vars(item) for item in data]
    return data


def load_config(path: Path | None = None, *, strict: bool = False) -> Config:
    """Load and validate config from YAML. Missing file → empty Config unless strict."""
    p = path or config_path()
    if not p.exists():
        if strict:
            raise ConfigFileNotFoundError(f"config file not found: {p}")
        return Config()

    yaml = YAML(typ="safe")
    raw = yaml.load(p.read_text()) or {}
    expanded = _expand_env_vars(raw)
    return Config.model_validate(expanded)
