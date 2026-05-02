"""`claude -p` subprocess runner for skill evals.

Drives the user's existing Claude Code subscription (no API key required).
The new skill is injected via --append-system-prompt so the eval tests the
content in *this* branch, not whatever skill is currently installed globally.

The runner parses stream-json output to capture:
- bash invocations the agent ran (so predicates can assert on commands used)
- the agent's final text reply
- duration / cost telemetry from the `result` event

Predicates in `tasks/tasks.py` consume the EvalResult — same shape as the
prior Anthropic-SDK runner so the task definitions need only minor tweaks.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

CLAUDE_BIN = "claude"
DEFAULT_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class EvalResult:
    success: bool
    turns: int
    bash_calls: list[str]
    final_text: str
    transcript_events: list[dict]
    stop_reason: str | None = None
    duration_ms: int | None = None
    total_cost_usd: float | None = None


@dataclass
class _ParsedStream:
    bash_calls: list[str] = field(default_factory=list)
    final_text: str = ""
    transcript_events: list[dict] = field(default_factory=list)
    num_turns: int = 0
    stop_reason: str | None = None
    duration_ms: int | None = None
    total_cost_usd: float | None = None


def _build_system_prompt_addendum(skill_corpus: dict[str, str]) -> str:
    """Concatenate SKILL.md + references into a system-prompt addendum.

    Each file is wrapped in <file path="..."> ... </file> so the agent can
    cite paths verbatim. SKILL.md frontmatter is preserved.
    """
    parts: list[str] = [
        "The following monday.com `mondo` CLI documentation is loaded for this session.",
        "Consult these files before improvising. Each section follows Goal / Command / Output / Gotcha.",
    ]
    skill = skill_corpus.get("SKILL.md")
    if skill:
        parts.append(f'<file path="SKILL.md">\n{skill}\n</file>')
    for rel_path in sorted(k for k in skill_corpus if k != "SKILL.md"):
        parts.append(f'<file path="{rel_path}">\n{skill_corpus[rel_path]}\n</file>')
    return "\n\n".join(parts)


def _parse_stream(stdout: str) -> _ParsedStream:
    """Walk stream-json output line by line and extract what predicates need."""
    parsed = _ParsedStream()
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        parsed.transcript_events.append(event)
        etype = event.get("type")
        if etype == "assistant":
            content = event.get("message", {}).get("content", []) or []
            for block in content:
                btype = block.get("type")
                if btype == "tool_use" and block.get("name") == "Bash":
                    cmd = (block.get("input") or {}).get("command", "")
                    if cmd:
                        parsed.bash_calls.append(cmd)
                elif btype == "text":
                    text = block.get("text") or ""
                    if text:
                        parsed.final_text = text
        elif etype == "result":
            parsed.final_text = event.get("result") or parsed.final_text
            parsed.num_turns = int(event.get("num_turns") or 0)
            parsed.stop_reason = event.get("stop_reason")
            parsed.duration_ms = event.get("duration_ms")
            parsed.total_cost_usd = event.get("total_cost_usd")
    return parsed


def run_skill_eval_via_claude(
    *,
    skill_corpus: dict[str, str],
    user_prompt: str,
    success_predicate: Callable[[EvalResult], bool],
    work_dir: Path,
    model: str = "claude-haiku-4-5",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    extra_env: dict[str, str] | None = None,
) -> EvalResult:
    """Run a single eval task via `claude -p`.

    Parameters
    ----------
    skill_corpus:
        SKILL.md + references/*.md keyed by relative path. Injected via
        --append-system-prompt so the eval reflects the in-branch content.
    user_prompt:
        The task prompt the agent sees.
    success_predicate:
        Called with the populated EvalResult; returns the success flag.
    work_dir:
        CWD for the `claude` subprocess. Should be an empty directory the
        agent can write into. The caller owns its lifecycle.
    model:
        Model alias passed to `claude --model`. Defaults to haiku-4-5 for cost.
    timeout_seconds:
        Hard wallclock cap. The subprocess is killed if exceeded.
    extra_env:
        Extra env vars merged on top of os.environ — typically MONDAY_API_TOKEN
        et al. so `mondo` invocations inside the session authenticate.
    """
    work_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    # Prevent `claude -p` from inheriting the parent CLAUDECODE flag (which
    # would otherwise refuse to nest a non-interactive session).
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)
    if extra_env:
        env.update(extra_env)

    addendum = _build_system_prompt_addendum(skill_corpus)
    cmd = [
        CLAUDE_BIN,
        "-p", user_prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
        "--no-session-persistence",
        "--model", model,
        "--append-system-prompt", addendum,
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=work_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return EvalResult(
            success=False,
            turns=0,
            bash_calls=[],
            final_text=f"timed out after {timeout_seconds}s",
            transcript_events=[],
            stop_reason="timeout",
        )

    parsed = _parse_stream(proc.stdout)
    if proc.returncode != 0 and not parsed.final_text:
        parsed.final_text = (
            f"claude -p exit={proc.returncode}\n--- stderr ---\n{proc.stderr[:2000]}"
        )

    interim = EvalResult(
        success=False,
        turns=parsed.num_turns,
        bash_calls=parsed.bash_calls,
        final_text=parsed.final_text,
        transcript_events=parsed.transcript_events,
        stop_reason=parsed.stop_reason,
        duration_ms=parsed.duration_ms,
        total_cost_usd=parsed.total_cost_usd,
    )
    return EvalResult(**{**interim.__dict__, "success": success_predicate(interim)})
