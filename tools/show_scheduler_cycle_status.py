#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.lower().endswith(" utc"):
        text = text[:-4].strip() + "+00:00"
    elif text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _iso(dt: Optional[datetime]) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z") if dt else ""


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _row_time(row: Dict[str, Any]) -> Optional[datetime]:
    return _parse_time(row.get("generated_at") or row.get("timestamp") or row.get("created_at") or row.get("decision_time"))


def _latest_jsonl_time(path: Path) -> Optional[datetime]:
    latest: Optional[datetime] = None
    for row in _iter_jsonl(path):
        ts = _row_time(row)
        if ts and (latest is None or ts > latest):
            latest = ts
    return latest


def _count_rows_since(path: Path, since: Optional[datetime]) -> int:
    if since is None:
        return 0
    count = 0
    for row in _iter_jsonl(path):
        ts = _row_time(row)
        if ts and ts >= since:
            count += 1
    return count


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _loop_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []


def _line_time(line: str) -> Optional[datetime]:
    match = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3}", line)
    if not match:
        return None
    return _parse_time(match.group(1).replace(" ", "T") + "Z")


def _latest_line_time(lines: list[str], pattern: str) -> Optional[datetime]:
    regex = re.compile(pattern)
    for line in reversed(lines):
        if regex.search(line):
            return _line_time(line)
    return None


def _latest_skip(lines: list[str]) -> tuple[Optional[datetime], str]:
    for line in reversed(lines):
        if "Skipping duplicate full cycle boundary" in line:
            return _line_time(line), line.strip()
    return None, ""


def _interval_hours(lines: list[str]) -> int:
    for line in reversed(lines):
        match = re.search(r"Bot Started \((\d+)H main interval", line)
        if match:
            return max(1, int(match.group(1)))
    return 4


def _next_hour_boundary(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def _next_full_cycle_boundary(now: datetime, interval_hours: int) -> datetime:
    boundary = _next_hour_boundary(now)
    while boundary.hour % max(1, interval_hours) != 0:
        boundary += timedelta(hours=1)
    return boundary


def _service_pid() -> str:
    try:
        result = subprocess.run(
            ["pgrep", "-af", "run_trader_loop.py"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except Exception:
        return ""
    for line in result.stdout.splitlines():
        parts = line.strip().split(maxsplit=1)
        if parts and "pgrep" not in line:
            return parts[0]
    return ""


def build_scheduler_cycle_status(*, root: str | Path = ".", now: Optional[datetime] = None) -> Dict[str, Any]:
    project_root = Path(root)
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    lines = _loop_lines(project_root / "logs/loop.log")
    interval = _interval_hours(lines)
    guard_state = _read_json(project_root / "state/run_trader_loop_cycles.json")
    last_boundary_key = str(guard_state.get("last_boundary_key") or "")
    last_full_cycle_boundary = last_boundary_key.split("full:", 1)[1] if last_boundary_key.startswith("full:") else ""
    last_started = _latest_line_time(lines, r"Starting new FULL trading cycle")
    last_completed = _latest_jsonl_time(project_root / "logs/cycle_summary.jsonl")
    last_heartbeat = _latest_jsonl_time(project_root / "logs/heartbeat_summary.jsonl")
    skip_at, skip_line = _latest_skip(lines)
    decision_since = last_started or last_completed
    decision_rows_since_last_full_cycle = _count_rows_since(project_root / "logs/analysis.jsonl", decision_since)
    latest_full_activity = max((ts for ts in (last_started, last_completed) if ts is not None), default=None)
    full_cycle_recently_skipped = bool(skip_at and (latest_full_activity is None or skip_at > latest_full_activity))
    skip_reason = ""
    if full_cycle_recently_skipped:
        skip_reason = "duplicate_boundary_guard: " + skip_line
    elif skip_line:
        skip_reason = "latest_duplicate_skip_preceded_latest_full_cycle_activity"

    return {
        "now_utc": _iso(now_utc),
        "service_pid": _service_pid(),
        "last_full_cycle_boundary": last_full_cycle_boundary,
        "last_full_cycle_started_at": _iso(last_started),
        "last_full_cycle_completed_at": _iso(last_completed),
        "last_heartbeat_at": _iso(last_heartbeat),
        "next_hour_boundary": _iso(_next_hour_boundary(now_utc)),
        "next_full_cycle_boundary": _iso(_next_full_cycle_boundary(now_utc, interval)),
        "duplicate_boundary_guard_state": guard_state,
        "full_cycle_recently_skipped": full_cycle_recently_skipped,
        "skip_reason": skip_reason,
        "decision_rows_since_last_full_cycle": decision_rows_since_last_full_cycle,
        "audit_data_available": (project_root / "logs/analysis.jsonl").exists(),
        "cycle_interval_hours": interval,
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_mutation_performed": False,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Show read-only scheduler/full-cycle status.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)
    report = build_scheduler_cycle_status(root=args.root)
    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json or not args.json_out:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
