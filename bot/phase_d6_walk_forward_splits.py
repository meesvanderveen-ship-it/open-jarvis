from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.phase_d6_baseline_backtest import load_d6_candles
from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_dataset_quality_aggregate import build_phase_d6_dataset_quality_aggregate_report


D6_WALK_FORWARD_SPLITS_PHASE = "D6_walk_forward_split_scaffold_v1"
D6_WALK_FORWARD_SPLIT_MODES = {"holdout", "rolling", "expanding"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _pct(part: int, total: int) -> str:
    if total <= 0:
        return "0"
    return format((part / total) * 100, ".6f").rstrip("0").rstrip(".")


def _range_from_indices(candles: List[Dict[str, Any]], start_idx: int, end_idx: int) -> Dict[str, Any]:
    count = max(end_idx - start_idx, 0)
    if count <= 0:
        return {
            "start_index": start_idx,
            "end_index_exclusive": end_idx,
            "count": 0,
            "first_candle_start": None,
            "last_candle_start": None,
        }
    return {
        "start_index": start_idx,
        "end_index_exclusive": end_idx,
        "count": count,
        "first_candle_start": candles[start_idx]["start"],
        "last_candle_start": candles[end_idx - 1]["start"],
    }


def _split_record(
    *,
    candles: List[Dict[str, Any]],
    split_index: int,
    mode: str,
    train: tuple[int, int],
    validation: tuple[int, int],
    test: tuple[int, int],
) -> Dict[str, Any]:
    return {
        "split_index": split_index,
        "split_mode": mode,
        "train": _range_from_indices(candles, *train),
        "validation": _range_from_indices(candles, *validation),
        "test": _range_from_indices(candles, *test),
    }


def _holdout_splits(candles: List[Dict[str, Any]], train_count: int, validation_count: int, test_count: int) -> List[Dict[str, Any]]:
    return [
        _split_record(
            candles=candles,
            split_index=0,
            mode="holdout",
            train=(0, train_count),
            validation=(train_count, train_count + validation_count),
            test=(train_count + validation_count, train_count + validation_count + test_count),
        )
    ]


def _rolling_splits(
    candles: List[Dict[str, Any]],
    train_count: int,
    validation_count: int,
    test_count: int,
    step_count: int,
    max_splits: int,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    start = 0
    idx = 0
    total = len(candles)
    window = train_count + validation_count + test_count
    while start + window <= total and idx < max_splits:
        train = (start, start + train_count)
        validation = (train[1], train[1] + validation_count)
        test = (validation[1], validation[1] + test_count)
        out.append(
            _split_record(
                candles=candles,
                split_index=idx,
                mode="rolling",
                train=train,
                validation=validation,
                test=test,
            )
        )
        start += step_count
        idx += 1
    return out


def _expanding_splits(
    candles: List[Dict[str, Any]],
    train_count: int,
    validation_count: int,
    test_count: int,
    step_count: int,
    max_splits: int,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    train_end = train_count
    idx = 0
    total = len(candles)
    while train_end + validation_count + test_count <= total and idx < max_splits:
        validation = (train_end, train_end + validation_count)
        test = (validation[1], validation[1] + test_count)
        out.append(
            _split_record(
                candles=candles,
                split_index=idx,
                mode="expanding",
                train=(0, train_end),
                validation=validation,
                test=test,
            )
        )
        train_end += step_count
        idx += 1
    return out


def _validate_counts(*, train_count: int, validation_count: int, test_count: int, step_count: int, max_splits: int) -> None:
    if train_count <= 0:
        raise ValueError("train_count_must_be_positive")
    if validation_count < 0:
        raise ValueError("validation_count_must_not_be_negative")
    if test_count <= 0:
        raise ValueError("test_count_must_be_positive")
    if step_count <= 0:
        raise ValueError("step_count_must_be_positive")
    if max_splits <= 0:
        raise ValueError("max_splits_must_be_positive")


def build_phase_d6_walk_forward_split_report(
    *,
    candles_path: str | Path,
    split_mode: str = "holdout",
    train_count: int = 210,
    validation_count: int = 70,
    test_count: int = 70,
    step_count: int = 70,
    max_splits: int = 12,
    require_quality_ready: bool = True,
) -> Dict[str, Any]:
    mode = str(split_mode or "").strip().lower()
    if mode not in D6_WALK_FORWARD_SPLIT_MODES:
        raise ValueError(f"unsupported_walk_forward_split_mode:{split_mode}")
    _validate_counts(
        train_count=int(train_count),
        validation_count=int(validation_count),
        test_count=int(test_count),
        step_count=int(step_count),
        max_splits=int(max_splits),
    )

    loaded = load_d6_candles(candles_path)
    candles = loaded["candles"]
    candle_count = len(candles)
    quality = build_phase_d6_dataset_quality_aggregate_report(candle_paths=[candles_path])
    quality_summary = dict(quality.get("summary") or {})
    warnings = [
        "research_walk_forward_split_scaffold_only",
        "not_backtest",
        "not_signal_generation",
        "not_parameter_search",
        "not_optimization",
    ]
    blockers: List[str] = []
    if require_quality_ready and not quality_summary.get("ready_for_walk_forward_scaffold"):
        blockers.append("dataset_quality_not_ready_for_walk_forward")
    if loaded.get("gap_count"):
        warnings.append("candle_gaps_detected")

    minimum_required = int(train_count) + int(validation_count) + int(test_count)
    if candle_count < minimum_required:
        blockers.append("insufficient_candles_for_requested_split")
        splits: List[Dict[str, Any]] = []
    elif mode == "holdout":
        splits = _holdout_splits(candles, int(train_count), int(validation_count), int(test_count))
    elif mode == "rolling":
        splits = _rolling_splits(
            candles,
            int(train_count),
            int(validation_count),
            int(test_count),
            int(step_count),
            int(max_splits),
        )
    else:
        splits = _expanding_splits(
            candles,
            int(train_count),
            int(validation_count),
            int(test_count),
            int(step_count),
            int(max_splits),
        )
    if not splits and "insufficient_candles_for_requested_split" not in blockers:
        blockers.append("no_splits_generated")

    usable = not blockers and bool(splits)
    return {
        "generated_at": _now_iso(),
        "phase": D6_WALK_FORWARD_SPLITS_PHASE,
        "status": "d6_walk_forward_splits_ready" if usable else "d6_walk_forward_splits_blocked",
        "candles_path": str(assert_research_path(candles_path)),
        "product_id": loaded["product_id"],
        "timeframe": loaded["timeframe"],
        "candle_count": candle_count,
        "first_candle_start": loaded["first_candle_start"],
        "last_candle_start": loaded["last_candle_start"],
        "gap_count": loaded["gap_count"],
        "split_mode": mode,
        "train_count": int(train_count),
        "validation_count": int(validation_count),
        "test_count": int(test_count),
        "step_count": int(step_count),
        "max_splits": int(max_splits),
        "split_count": len(splits),
        "splits": splits,
        "split_coverage": {
            "minimum_required_candles": minimum_required,
            "first_split_uses_pct": _pct(minimum_required, candle_count),
            "full_dataset_candle_count": candle_count,
        },
        "dataset_quality": {
            "aggregate_quality_class": quality_summary.get("aggregate_quality_class"),
            "ready_for_walk_forward_scaffold": quality_summary.get("ready_for_walk_forward_scaffold"),
            "blockers": list(quality_summary.get("blockers") or []),
        },
        "usable_for_future_research": usable,
        "warnings": warnings,
        "blockers": blockers,
        "research_only": True,
        "no_live_action": True,
        "no_coinbase_call": True,
        "state_write_performed": False,
        "no_bulk_fetch": True,
        "no_optimization": True,
        "parameter_search_performed": False,
        "learning_to_execution_allowed": False,
        "parameter_change_allowed": False,
    }


def write_walk_forward_split_report(report: Dict[str, Any], output_path: str | Path) -> Path:
    path = assert_research_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


__all__ = [
    "D6_WALK_FORWARD_SPLITS_PHASE",
    "D6_WALK_FORWARD_SPLIT_MODES",
    "build_phase_d6_walk_forward_split_report",
    "write_walk_forward_split_report",
]
