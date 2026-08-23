#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_all_ticker_24h_post_run_evidence_pack import build_all_ticker_24h_post_run_evidence_pack, render_all_ticker_24h_post_run_evidence_pack_markdown  # noqa: E402


def _write(path: Path, text: str) -> None:
    target = path if path.is_absolute() else PROJECT_ROOT / path
    target = target.resolve()
    if not str(target).startswith(str((PROJECT_ROOT / "reports").resolve())):
        raise SystemExit("output must be under reports/")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build all-ticker post-run evidence scaffold. No Coinbase calls.")
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument("--start-utc", default="")
    parser.add_argument("--stop-utc", default="")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--markdown-out", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()
    report = build_all_ticker_24h_post_run_evidence_pack(root=args.root, start_utc=args.start_utc, stop_utc=args.stop_utc)
    js = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    md = render_all_ticker_24h_post_run_evidence_pack_markdown(report)
    if args.json_out:
        _write(Path(args.json_out), js)
    if args.markdown_out:
        _write(Path(args.markdown_out), md)
    if args.markdown:
        print(md, end="")
    elif args.json or not (args.json_out or args.markdown_out):
        print(js, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
