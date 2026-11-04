#!/usr/bin/env python3
"""Classify Bambu Studio windows. Never emits a close or click command.

Usage:
  studio_windows.py inventory --text windows.tsv
  studio_windows.py inventory --json windows.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROTECTED = "send print job"


def classify(windows: list[dict]) -> dict:
    protected, other = [], []
    for window in windows:
        title = str(window.get("title", ""))
        item = {"id": str(window.get("id", "")), "title": title}
        if PROTECTED in title.lower():
            protected.append(item)
        else:
            other.append(item)
    return {
        "protected": protected,
        "other": other,
        "close": [],
        "click": [],
        "note": "Do not close, raise, focus, or click a Send print job window.",
    }


def parse_text(text: str) -> list[dict]:
    windows = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "\t" not in stripped:
            raise ValueError(f"expected id<TAB>title: {stripped}")
        ident, title = stripped.split("\t", 1)
        windows.append({"id": ident.strip(), "title": title.strip()})
    return windows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify Studio windows without touching them")
    sub = parser.add_subparsers(dest="command", required=True)
    inventory = sub.add_parser("inventory")
    source = inventory.add_mutually_exclusive_group(required=True)
    source.add_argument("--text")
    source.add_argument("--json")
    args = parser.parse_args(argv)
    try:
        if args.text:
            windows = parse_text(Path(args.text).read_text())
        else:
            windows = json.loads(Path(args.json).read_text())
            if not isinstance(windows, list):
                raise ValueError("window JSON must be a list")
        print(json.dumps(classify(windows), indent=2))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"WINDOWS: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
