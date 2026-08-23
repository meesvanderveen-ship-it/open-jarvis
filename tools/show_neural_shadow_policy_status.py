#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.config import BotConfig
from bot.neural_shadow_policy import neural_learning_status_from_config


def build_neural_shadow_policy_status(*, root: str | Path = ".") -> dict:
    try:
        cfg = BotConfig()
        cfg.validate()
        status = neural_learning_status_from_config(cfg, root=root)
        status["config_valid"] = True
        status["config_error"] = ""
    except Exception as exc:
        class _Fallback:
            neural_shadow_policy_enabled = True
            neural_shadow_policy_training_enabled = True
            neural_shadow_policy_execution_allowed = False
            neural_shadow_policy_agreement_required = False
            neural_shadow_policy_model_path = "state/neural_shadow_policy.json"
            neural_shadow_policy_report_path = "reports/live_learning/neural-shadow-policy-latest.json"

        status = neural_learning_status_from_config(_Fallback(), root=root)
        status["config_valid"] = False
        status["config_error"] = str(exc)
    return {
        "phase": "neural_shadow_policy_status_v1",
        "read_only": True,
        "coinbase_call_attempted": False,
        "llm_call_attempted": False,
        "neural_learning_status": status,
        "neural_shadow_passivity": {
            "execution_allowed": bool(status.get("execution_allowed")),
            "one_class_dataset_warning": bool(status.get("one_class_dataset_warning")),
            "neural_shadow_one_class_passivity_bias": bool(status.get("neural_shadow_one_class_passivity_bias")),
            "balanced_label_recommendation": status.get("balanced_label_recommendation"),
        },
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show neural shadow policy status.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--root", default=".")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_neural_shadow_policy_status(root=args.root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        s = report["neural_learning_status"]
        print(f"status={s['status']} model_available={s['model_available']} execution_allowed={s['execution_allowed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_neural_shadow_policy_status", "main", "parse_args"]
