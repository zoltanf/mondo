#!/usr/bin/env python3
"""Scan local Claude Code session logs for `mondo` CLI + skill usage.

Finds every `mondo` bash invocation and every `mondo` *skill* invocation across
the user's session transcripts since a cutoff (default: the commit date of the
most recent `vX.Y.Z` git tag in the Mondo repo), captures each command's
result / error / latency / payload size, and prints an aggregated summary for
usability + performance analysis. The full record set is also written to JSON
so the agent can drill into anything the summary only counts.

This consolidates the four ad-hoc scripts the original audit session wrote to
/tmp. The numbers it prints are the raw material; the narrative judgement
(root causes, what to fix, what to ignore) is the agent's job — see SKILL.md.

Usage:
    python3 scan_mondo_usage.py                 # since latest vX.Y.Z tag
    python3 scan_mondo_usage.py --since 2026-05-31T17:23:00+00:00
    python3 scan_mondo_usage.py --repo /path/to/Mondo --top 60
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import statistics
import subprocess
import sys
from datetime import datetime, timezone

# A `mondo` invocation at a command boundary (start of line, after ; & | or `(`).
# Avoids matching e.g. "salmondo" or a path containing the substring.
MONDO_CMD_RE = re.compile(r"(?:^|[\s;&|(])mondo\s+", re.M)

# Recently-shipped sugar worth a usage probe — near-zero counts here mean a
# discoverability gap (the feature exists but agents don't reach for it), not a
# capability gap. Extend this list as new features ship.
FEATURE_PROBES = [
    "--batch", "item find", "--poll-until", "--max-items", "--columns",
    "--fields", "column get-meta", "column labels", "mondo export",
    "mondo import", "file upload", "file download", "file url",
]


def strip_noise(cmd):
    """Blank out heredoc bodies and quoted strings before looking for `mondo`.

    Without this, a `mondo` mentioned inside a `git commit -m "...mondo..."`
    message, an `echo "run mondo ..."`, or a `gh issue create --body "$(cat
    <<'EOF' ... mondo ... EOF)"` heredoc gets counted as a real invocation —
    which badly pollutes the frequency table when scanning the Mondo repo's own
    dev sessions. We only count `mondo` that survives in executable position.
    """
    # heredoc bodies: <<['"]?MARKER ... <newline>MARKER
    cmd = re.sub(r"<<-?\s*(['\"]?)(\w+)\1.*?^\s*\2\b", " ", cmd, flags=re.S | re.M)
    # simple quoted strings (our inputs don't nest escaped quotes meaningfully)
    cmd = re.sub(r"'[^']*'", " ", cmd)
    cmd = re.sub(r'"[^"]*"', " ", cmd)
    return cmd


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def resolve_cutoff(args):
    """Return (cutoff_datetime, label). Prefer --since; else newest git tag."""
    if args.since:
        dt = parse_ts(args.since)
        if not dt:
            sys.exit(f"--since not an ISO timestamp: {args.since!r}")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt, f"--since {args.since}"

    def git(*a):
        return subprocess.run(
            ["git", "-C", args.repo, *a],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    try:
        tag = git("tag", "--list", "v*", "--sort=-creatordate").splitlines()[0]
        iso = git("log", "-1", "--format=%aI", tag)
    except (subprocess.CalledProcessError, IndexError, FileNotFoundError):
        sys.exit(
            "Could not auto-detect the last release tag. Run from the Mondo "
            "repo, pass --repo /path/to/Mondo, or pass --since <ISO timestamp>."
        )
    dt = parse_ts(iso)
    return dt, f"{tag} ({iso})"


def _verb(tok):
    """Does `tok` look like a real `mondo` group/verb, vs a redirection
    (`2>&1`), a value (`id,title,type`), or a path the noise stripper missed?"""
    return bool(tok and not tok.startswith(("-", "'", '"', "$"))
                and not tok[0].isdigit() and not re.search(r"[<>/,|]", tok))


def subcmd(cmd):
    """Best-effort `mondo <group> <verb>` extraction for frequency counting."""
    cmd = strip_noise(cmd)
    m = re.search(r"(?:^|[\s;&|(])mondo\s+(--?\S+\s+)*(\S+)(?:\s+(\S+))?", cmd)
    if not m:
        return "?"
    first, second = m.group(2), m.group(3) or ""
    if first in ("--help", "-h"):
        return "--help"
    if not _verb(first):
        return "?"  # bare `mondo` or an unparseable artifact
    return f"{first} {second}" if _verb(second) else first


def scan(cutoff, root, repo, include_self):
    """Single pass over every transcript newer than the cutoff.

    Returns (invocations, skill_invocations, sessions, n_files, n_excluded).
    `sessions` maps a transcript path to its context flags (skill-loaded / read
    refs / headless / first user message). Unless `include_self`, the Mondo
    repo's own project transcripts are skipped — they're full of commit
    messages, `gh issue` bodies and benchmark scripts that mention `mondo` but
    aren't consumer usage. Claude Code names a project dir after its cwd with
    `/` turned into `-`, so the repo at /a/b/Mondo lives in `-a-b-Mondo`.
    """
    self_slug = os.path.abspath(repo).replace("/", "-") if repo else None

    files, n_excluded = [], 0
    for f in glob.glob(os.path.join(root, "*", "*.jsonl")):
        if not include_self and self_slug and os.path.basename(os.path.dirname(f)) == self_slug:
            n_excluded += 1
            continue
        try:
            mt = datetime.fromtimestamp(os.path.getmtime(f), tz=timezone.utc)
        except OSError:
            continue
        if mt >= cutoff:
            files.append(f)

    invocations, skill_invocations = [], []
    sessions = {}

    for path in files:
        pending = {}  # tool_use_id -> invocation dict awaiting its result
        ctx = {"skill_loaded": False, "read_refs": 0, "headless": False,
               "first_user": "", "n_inv": 0, "n_help": 0}
        sessions[path] = ctx
        try:
            fh = open(path, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if "CLAUDE_JOB_DIR" in line or '"source":"cron"' in line:
                    ctx["headless"] = True
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = parse_ts(rec.get("timestamp", ""))
                msg = rec.get("message") or {}
                content = msg.get("content")

                if (rec.get("type") == "user" and isinstance(content, str)
                        and not ctx["first_user"]):
                    ctx["first_user"] = content[:100].replace("\n", " ")

                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    bt = block.get("type")
                    if bt == "tool_use":
                        name = block.get("name", "")
                        inp = block.get("input") or {}
                        if name == "Bash":
                            cmd = inp.get("command", "")
                            clean = strip_noise(cmd)
                            if MONDO_CMD_RE.search(clean):
                                inv = {"file": path, "ts": ts, "command": cmd,
                                       "error": None, "result": "", "dur": None,
                                       "rsize": 0}
                                invocations.append(inv)
                                pending[block.get("id")] = inv
                                ctx["n_inv"] += 1
                                if "--help" in clean or re.search(r"\s-h\b", clean):
                                    ctx["n_help"] += 1
                        elif name == "Skill":
                            if "mondo" in inp.get("skill", ""):
                                ctx["skill_loaded"] = True
                                skill_invocations.append(
                                    {"file": path, "ts": rec.get("timestamp", ""),
                                     "skill": inp.get("skill", ""),
                                     "args": inp.get("args", "")})
                        elif name == "Read":
                            if "skills/mondo" in str(inp.get("file_path", "")):
                                ctx["read_refs"] += 1
                    elif bt == "tool_result":
                        inv = pending.pop(block.get("tool_use_id"), None)
                        if inv is None:
                            continue
                        inv["error"] = bool(block.get("is_error"))
                        c = block.get("content")
                        if isinstance(c, list):
                            txt = "\n".join(b.get("text", "") for b in c
                                            if isinstance(b, dict))
                        else:
                            txt = str(c) if c else ""
                        inv["rsize"] = len(txt)
                        inv["result"] = txt[:3000]
                        if ts and inv["ts"]:
                            inv["dur"] = (ts - inv["ts"]).total_seconds()

    return invocations, skill_invocations, sessions, len(files), n_excluded


def proj(path):
    return path.split("/")[-2].replace("-Users-zoltanf-Development-", "")[:34]


def hr(title):
    print(f"\n{'=' * 4} {title} {'=' * (66 - len(title))}")


def report(invs, skills, sessions, n_files, n_excluded, label, top, json_out):
    n_err = sum(1 for i in invs if i["error"])
    bash_files = {i["file"] for i in invs}
    skill_sessions = {s["file"] for s in skills}
    helps = [i for i in invs if "--help" in i["command"] or re.search(r"\s-h\b", i["command"])]
    gql = [i for i in invs if re.search(r"mondo\s+graphql", strip_noise(i["command"]))]
    devnull = [i for i in invs if "2>/dev/null" in i["command"]]
    cold = bash_files - skill_sessions

    hr("SCOPE")
    print(f"cutoff:                 {label}")
    print(f"transcripts scanned:    {n_files}"
          + (f"  ({n_excluded} Mondo-repo dev transcripts excluded; --include-self to keep)"
             if n_excluded else ""))
    print(f"sessions using mondo:    {len(bash_files)}  "
          f"(skill-loaded: {len(bash_files & skill_sessions)}, cold: {len(cold)})")
    print(f"mondo CLI invocations:   {len(invs)}")
    print(f"  errored:               {n_err}"
          + (f"  ({100 * (len(invs) - n_err) // len(invs)}% success)" if invs else ""))
    print(f"mondo skill invocations: {len(skills)}")
    print(f"--help lookups:          {len(helps)}")
    print(f"raw graphql escapes:     {len(gql)}")
    print(f"stderr-suppressed (2>/dev/null): {len(devnull)}"
          + (f"  ({100 * len(devnull) // len(invs)}% of calls)" if invs else ""))

    hr(f"SUBCOMMAND FREQUENCY (top {top})")
    for k, v in collections.Counter(subcmd(i["command"]) for i in invs).most_common(top):
        print(f"{v:4d}  {k}")

    hr("PER-SESSION CONTEXT  (tag: SKILL=loaded skill, REFS=read skill files, COLD=neither)")
    for path, c in sorted(sessions.items(), key=lambda kv: -kv[1]["n_inv"]):
        if c["n_inv"] == 0:
            continue
        tag = "SKILL" if path in skill_sessions else ("REFS " if c["read_refs"] else "COLD ")
        job = "JOB" if c["headless"] else "   "
        print(f"{tag} {job} inv={c['n_inv']:3d} help={c['n_help']:2d} refs={c['read_refs']:2d} "
              f"{proj(path):36s} | {c['first_user'][:64]}")

    hr(f"ERRORS ({n_err})")
    for i in invs:
        if i["error"]:
            print("-" * 72)
            print(f"{(i['ts'].isoformat()[:19] if i['ts'] else '?'):19} {proj(i['file'])}")
            print("CMD:", i["command"][:300].replace("\n", " "))
            print("RES:", i["result"][:500].replace("\n", " | "))

    hr(f"RAW GRAPHQL ESCAPES ({len(gql)})")
    for g in gql:
        print(f"--- {proj(g['file'])}")
        print("   ", g["command"][:300].replace("\n", " "))

    hr("FRICTION SIGNALS")
    qmis = [i for i in invs if re.search(r"mondo\s+graphql\s+--query", i["command"])]
    ojson = [i for i in invs if re.search(r"-o json|--output json", i["command"])]
    nocache = [i for i in invs if "--no-cache" in i["command"]]
    silent_err = [i for i in invs if i["error"] and "2>/dev/null" in i["command"]
                  and len((i["result"] or "").strip()) < 60]
    print(f"`graphql --query` misuse (query is positional):  {len(qmis)}")
    print(f"redundant `-o json` (auto when piped):           {len(ojson)}")
    print(f"`--no-cache` usage:                              {len(nocache)}")
    print(f"errors with output hidden by 2>/dev/null:        {len(silent_err)}")

    # error-recovery: an errored call followed by another mondo call <180s later
    by_file = collections.defaultdict(list)
    for i in invs:
        if i["ts"]:
            by_file[i["file"]].append(i)
    recoveries = 0
    for seq in by_file.values():
        seq.sort(key=lambda x: x["ts"])
        for a, b in zip(seq, seq[1:]):
            if a["error"] and (b["ts"] - a["ts"]).total_seconds() < 180:
                recoveries += 1
    print(f"errors followed by a retry within 180s:          {recoveries}")

    hr("FEATURE-USAGE PROBES (low/zero = discoverability gap, not capability gap)")
    for feat in FEATURE_PROBES:
        print(f"{sum(1 for i in invs if feat in i['command']):4d}  {feat}")

    # ---- performance ----
    # `timed` = every call we could time. `single` = exactly one mondo call in
    # the bash block, so the wall-clock is attributable to mondo (not to echo /
    # git / loops / `/usr/bin/time` wrappers that merely contain a mondo call).
    # Gaps >300s are idle/approval waits, not latency — exclude from aggregates.
    timed = [i for i in invs if i["dur"] is not None
             and not (i["error"] and "denied" in (i["result"] or ""))]
    single = [i for i in timed
              if len(re.findall(r"mondo\s", i["command"])) == 1]
    attributable = [i for i in single if i["dur"] <= 300]
    idle = sum(1 for i in timed if i["dur"] > 300)
    hr("PERFORMANCE — LATENCY")
    if attributable:
        durs = sorted(i["dur"] for i in attributable)

        def pct(p):
            return durs[min(len(durs) - 1, int(p / 100 * len(durs)))]

        print(f"single-call invocations timed: {len(attributable)}  "
              f"(of {len(timed)} timed; {idle} idle/approval gaps >300s excluded)")
        print(f"latency s: p50={pct(50):.1f} p75={pct(75):.1f} p90={pct(90):.1f} "
              f"p95={pct(95):.1f} max={durs[-1]:.1f}")
        print(f"total wall time in attributable mondo calls: {sum(durs) / 60:.1f} min")

        print("\nslowest 15 single mondo calls:")
        for i in sorted(attributable, key=lambda x: -x["dur"])[:15]:
            print(f"  {i['dur']:7.1f}s  {i['command'][:120].replace(chr(10), ' ')}")

        by_sub = collections.defaultdict(list)
        for i in attributable:
            by_sub[subcmd(i["command"])].append(i["dur"])
        print("\nmedian latency by subcommand (single call per bash, n>=4):")
        for k, v in sorted(by_sub.items(), key=lambda kv: -statistics.median(kv[1])):
            if len(v) >= 4:
                print(f"  {statistics.median(v):6.1f}s median  n={len(v):3d}  "
                      f"max={max(v):6.1f}  {k}")
    else:
        print("no attributable single-call invocations in window")

    hr("PERFORMANCE — PAYLOAD & REDUNDANCY")
    if timed:
        rs = sorted(i["rsize"] for i in timed)
        print(f"result size bytes: p50={rs[len(rs) // 2]} "
              f"p90={rs[int(0.9 * len(rs))]} max={rs[-1]}")
        big = [i for i in timed if i["rsize"] > 30000]
        print(f"results >30KB dumped into context: {len(big)}")
        for i in sorted(big, key=lambda x: -x["rsize"])[:8]:
            print(f"  {i['rsize']:7d}B  {i['command'][:100].replace(chr(10), ' ')}")
    rep = collections.Counter((i["file"], i["command"].strip()) for i in invs)
    n_rep = sum(c - 1 for c in rep.values() if c > 1)
    print(f"\nredundant repeats (identical command, same session): {n_rep}")
    for (_, c), n in rep.most_common(6):
        if n > 1:
            print(f"  x{n}  {c[:100].replace(chr(10), ' ')}")
    board_list = collections.Counter()
    for i in invs:
        for m in re.finditer(r"item list --board[= ]+(\d+)", i["command"]):
            board_list[(i["file"], m.group(1))] += 1
    multi = {k: v for k, v in board_list.items() if v > 2}
    print(f"sessions re-listing the same board 3+ times: {len(multi)}")
    rate = [i for i in invs if i["result"]
            and re.search(r"complexity|rate limit|429|retry_in", i["result"], re.I)]
    print(f"rate-limit / complexity mentions in results: {len(rate)}")

    # ---- full dump for drill-down ----
    dump = {
        "cutoff": label,
        "n_files": n_files,
        "invocations": [{**i, "ts": i["ts"].isoformat() if i["ts"] else None}
                        for i in invs],
        "skill_invocations": skills,
    }
    with open(json_out, "w") as fh:
        json.dump(dump, fh, indent=1)
    print(f"\nfull record set written to {json_out} "
          f"({len(invs)} invocations) — grep/jq it for anything above.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", help="ISO timestamp cutoff; overrides tag auto-detect")
    ap.add_argument("--repo", default=os.getcwd(),
                    help="Mondo repo path for tag auto-detect (default: cwd)")
    ap.add_argument("--root", default=os.path.expanduser("~/.claude/projects"),
                    help="session-logs root (default: ~/.claude/projects)")
    ap.add_argument("--json-out", default="/tmp/mondo_usage.json",
                    help="where to write the full record set")
    ap.add_argument("--top", type=int, default=40, help="subcommands to list")
    ap.add_argument("--include-self", action="store_true",
                    help="keep the Mondo repo's own dev transcripts "
                         "(excluded by default — they're not consumer usage)")
    args = ap.parse_args()

    cutoff, label = resolve_cutoff(args)
    invs, skills, sessions, n_files, n_excluded = scan(
        cutoff, args.root, args.repo, args.include_self)
    report(invs, skills, sessions, n_files, n_excluded, label, args.top, args.json_out)


if __name__ == "__main__":
    main()
