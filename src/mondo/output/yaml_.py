"""YAML formatter (ruamel.yaml, safe-dump style)."""

from __future__ import annotations

from typing import Any, TextIO


def render(data: Any, stream: TextIO, tty: bool) -> None:
    from ruamel.yaml import YAML

    y = YAML(typ="safe")
    y.default_flow_style = False
    y.allow_unicode = True
    y.dump(data, stream)
