#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import BotConfig
from bot.phase_d32_llm_pre_live_health import build_phase_d32_llm_pre_live_health_report


def print_report(report):
    print("Phase D.3.2 LLM pre-live provider health")
    print("==========================================")
    print("status:", report.get("status"))
    print("ready:", report.get("ready"))
    print("window:", json.dumps(report.get("window", {}), ensure_ascii=False, sort_keys=True))
    print("config_flags:", json.dumps(report.get("config_flags", {}), ensure_ascii=False, sort_keys=True))
    print("counts:", json.dumps(report.get("counts", {}), ensure_ascii=False, sort_keys=True))
    print("Blockers:", json.dumps(report.get("blockers", []), ensure_ascii=False))
    print("Warnings:", json.dumps(report.get("warnings", []), ensure_ascii=False))
    print("Safety: D.3.2 leest alleen lokale logs/config en plaatst geen orders of provider-calls.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Controleer pre-live LLM/provider log health voor C.4.3 entry-only arming.")
    parser.add_argument("--json", action="store_true", help="Print volledige JSON-output")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT), help="Projectroot")
    parser.add_argument("--max-lines", type=int, default=5000, help="Max aantal logregels per bestand")
    args = parser.parse_args()

    cfg = BotConfig()
    cfg.validate()
    report = build_phase_d32_llm_pre_live_health_report(cfg=cfg, project_root=Path(args.project_root), max_lines=max(1, args.max_lines))
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
