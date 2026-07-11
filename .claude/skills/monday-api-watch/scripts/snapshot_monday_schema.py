#!/usr/bin/env python3
"""Snapshot the monday.com GraphQL schema as normalized, diffable text.

Emits one sorted line per type/field/arg/enum-value, including deprecation
markers, so `diff` between two snapshots shows exactly what monday changed.

Usage:
    MONDAY_API_TOKEN=... python3 snapshot_monday_schema.py --api-version 2026-07 > 2026-07.txt
    python3 snapshot_monday_schema.py --versions          # list available API versions

Token resolution: $MONDAY_API_TOKEN, else MONDAY_API_TOKEN= line in ./.env.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

API_URL = "https://api.monday.com/v2"

INTROSPECTION = """
query {
  __schema {
    queryType { name }
    mutationType { name }
    types {
      kind name
      fields(includeDeprecated: true) {
        name isDeprecated deprecationReason
        args { name type { ...T } defaultValue }
        type { ...T }
      }
      inputFields { name type { ...T } defaultValue }
      enumValues(includeDeprecated: true) { name isDeprecated deprecationReason }
      interfaces { name }
      possibleTypes { name }
    }
  }
}
fragment T on __Type {
  kind name
  ofType { kind name ofType { kind name ofType { kind name ofType { kind name } } } }
}
"""

VERSIONS_QUERY = "query { versions { kind value display_name } }"


def _token() -> str:
    tok = os.environ.get("MONDAY_API_TOKEN")
    if not tok and os.path.exists(".env"):
        for line in open(".env"):
            if line.startswith("MONDAY_API_TOKEN="):
                tok = line.split("=", 1)[1].strip()
                break
    if not tok:
        sys.exit("error: MONDAY_API_TOKEN not set (env or ./.env)")
    return tok


def _post(query: str, api_version: str | None) -> dict:
    headers = {"Authorization": _token(), "Content-Type": "application/json"}
    if api_version:
        headers["API-Version"] = api_version
    req = urllib.request.Request(API_URL, json.dumps({"query": query}).encode(), headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.load(resp)
    if body.get("errors"):
        sys.exit(f"error: {body['errors']}")
    return body["data"]


def _typeref(t: dict | None) -> str:
    if t is None:
        return "?"
    if t["kind"] == "NON_NULL":
        return _typeref(t.get("ofType")) + "!"
    if t["kind"] == "LIST":
        return "[" + _typeref(t.get("ofType")) + "]"
    return t.get("name") or "?"


def _dep(node: dict) -> str:
    if node.get("isDeprecated"):
        reason = (node.get("deprecationReason") or "").replace("\n", " ").strip()
        return f"  [deprecated: {reason}]"
    return ""


def snapshot(api_version: str) -> list[str]:
    schema = _post(INTROSPECTION, api_version)["__schema"]
    lines: list[str] = []
    for t in schema["types"]:
        name = t["name"]
        if name.startswith("__"):
            continue
        lines.append(f"{t['kind']} {name}")
        for f in t.get("fields") or []:
            args = ", ".join(
                f"{a['name']}: {_typeref(a['type'])}" for a in sorted(f["args"], key=lambda a: a["name"])
            )
            sig = f"({args})" if args else ""
            lines.append(f"{name}.{f['name']}{sig}: {_typeref(f['type'])}{_dep(f)}")
        for f in t.get("inputFields") or []:
            lines.append(f"{name}.{f['name']}: {_typeref(f['type'])}")
        for v in t.get("enumValues") or []:
            lines.append(f"{name}::{v['name']}{_dep(v)}")
    return sorted(lines)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--api-version", default=None, help="API-Version header, e.g. 2026-07")
    p.add_argument("--versions", action="store_true", help="list available API versions and exit")
    args = p.parse_args()

    if args.versions:
        for v in _post(VERSIONS_QUERY, None)["versions"]:
            print(f"{v['value']:<10} {v['kind']:<12} {v['display_name']}")
        return

    if not args.api_version:
        p.error("--api-version is required (or use --versions)")
    print("\n".join(snapshot(args.api_version)))


if __name__ == "__main__":
    main()
