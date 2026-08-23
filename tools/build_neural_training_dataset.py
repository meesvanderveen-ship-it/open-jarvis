#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.atomic_io import atomic_write_json, atomic_write_text
from bot.neural_feature_schema import DATASET_PATH, DATASET_SUMMARY_PATH, build_sample, now_iso
from bot.neural_reward_model import summarize_rewards


INPUT_PATHS = [
    "state/decision_outcomes.json",
    "logs/decision_outcomes.jsonl",
    "logs/execution_outcomes.jsonl",
    "logs/trade_reflections.jsonl",
    "logs/trade_learning_report.json",
    "reports/live_learning/live-learning-context-latest.json",
    "reports/live_learning/cost-aware-backlearning-latest.json",
    "reports/live_learning/start-parameter-candidates-latest.json",
    "state/open_orders.json",
    "state/positions.json",
]


def _load_json(path: Path) -> Tuple[List[Dict[str, Any]], int, bool]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], 0, False
    except Exception:
        return [], 1, True
    rows: List[Dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in ("outcomes", "records", "decisions", "orders", "positions", "candidates"):
            value = payload.get(key)
            if isinstance(value, list):
                rows.extend([x for x in value if isinstance(x, dict)])
            elif isinstance(value, dict):
                rows.extend([x for x in value.values() if isinstance(x, dict)])
        if not rows:
            rows.append(payload)
    elif isinstance(payload, list):
        rows.extend([x for x in payload if isinstance(x, dict)])
    return rows, 0, True


def _load_jsonl(path: Path) -> Tuple[List[Dict[str, Any]], int, bool]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return [], 0, False
    except Exception:
        return [], 1, True
    rows: List[Dict[str, Any]] = []
    corrupt = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except Exception:
            corrupt += 1
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows, corrupt, True


def _iter_d6(root: Path) -> Iterable[Path]:
    d6 = root / "reports/d6"
    if not d6.exists():
        return []
    return sorted(d6.glob("*.json"), key=lambda p: p.stat().st_mtime if p.exists() else 0)[-200:]


def build_neural_training_dataset(
    *,
    root: str | Path = ".",
    dataset_out: str | Path = DATASET_PATH,
    json_out: str | Path = DATASET_SUMMARY_PATH,
) -> Dict[str, Any]:
    project_root = Path(root)
    rows: List[Dict[str, Any]] = []
    sources: Dict[str, Dict[str, Any]] = {}
    generated = now_iso()

    paths = [project_root / p for p in INPUT_PATHS]
    paths.extend(_iter_d6(project_root))
    for path in paths:
        rel = str(path.relative_to(project_root)) if path.is_absolute() or path.exists() else str(path)
        if path.suffix == ".jsonl":
            loaded, corrupt, exists = _load_jsonl(path)
        else:
            loaded, corrupt, exists = _load_json(path)
        sources[rel] = {"available": exists, "records_loaded": len(loaded), "corrupt_records": corrupt}
        for idx, item in enumerate(loaded):
            try:
                rows.append(build_sample(item, source_name=rel, index=idx, created_at=generated))
            except Exception:
                sources[rel]["corrupt_records"] += 1

    unique: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        unique[str(row["sample_id"])] = row
    rows = list(unique.values())

    out_path = project_root / dataset_out if not Path(dataset_out).is_absolute() else Path(dataset_out)
    text = "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows)
    atomic_write_text(out_path, text)
    reward_summary = summarize_rewards(rows, output_path=project_root / "reports/live_learning/neural-reward-summary-latest.json")
    target_counts: Dict[str, int] = {}
    for row in rows:
        target = str(row.get("target_class") or "wait")
        target_counts[target] = target_counts.get(target, 0) + 1
    nonzero_targets = [name for name, count in target_counts.items() if int(count or 0) > 0]
    one_class = len(nonzero_targets) <= 1 and bool(target_counts)
    summary = {
        "phase": "neural_training_dataset_v1",
        "generated_at": generated,
        "dataset_path": str(dataset_out),
        "sample_count": len(rows),
        "target_counts": target_counts,
        "supported_balanced_labels": [
            "missed_opportunity",
            "bad_wait",
            "good_wait",
            "good_entry_candidate",
            "bad_entry_candidate",
            "good_probe_candidate",
            "bad_probe_candidate",
            "correct_avoid",
            "false_positive_plan",
            "trigger_ready_but_waited",
            "planner_no_plan_missed_move",
        ],
        "one_class_dataset_warning": one_class,
        "neural_shadow_one_class_passivity_bias": bool(one_class and target_counts.get("prefer_no_trade") == len(rows)),
        "balanced_label_recommendation": "bounded exploration needed for balanced labels",
        "sources": sources,
        "missing_feature_policy": "missing numeric features are null in dataset and encoded as 0.0 for model training; missing categories use unknown; missing booleans use false",
        "reward_summary_path": "reports/live_learning/neural-reward-summary-latest.json",
        "reward_summary": reward_summary,
        "coinbase_call_attempted": False,
        "llm_call_attempted": False,
        "live_order_action_attempted": False,
    }
    summary_path = project_root / json_out if not Path(json_out).is_absolute() else Path(json_out)
    atomic_write_json(summary_path, summary)
    return summary


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build local neural shadow training dataset.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--dataset-out", default=str(DATASET_PATH))
    parser.add_argument("--json-out", default=str(DATASET_SUMMARY_PATH))
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_neural_training_dataset(root=args.root, dataset_out=args.dataset_out, json_out=args.json_out)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_neural_training_dataset", "main", "parse_args"]
