"""Gate for benign stderr notices (#25).

A third of observed agent invocations append `2>/dev/null`, partly because
mondo emits benign noise (cache-hit notices) on stderr in non-interactive
runs — training the habit that stderr is junk, which then hides real
errors. Benign notices now show only when a human is plausibly watching
(stderr is a TTY) or when explicitly requested (`--verbose` /
`MONDO_VERBOSE=1`). Errors are unaffected — they always go to stderr.

Skill-freshness warnings are exempt from this gate (#75): agent (non-TTY)
runs are the audience consuming the skill, so `_skill_freshness` warns
them too, rate-limited instead of gated.
"""

from __future__ import annotations

import os
import sys


def benign_notices_enabled(*, verbose: bool = False) -> bool:
    """True when benign notices should be written to stderr."""
    if verbose or os.environ.get("MONDO_VERBOSE") == "1":
        return True
    return sys.stderr.isatty()
