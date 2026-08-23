#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.neural_feature_schema import DATASET_PATH
from bot.atomic_io import atomic_write_json
from bot.neural_shadow_policy import DEFAULT_MODEL_PATH, DEFAULT_REPORT_PATH, load_jsonl, train_shadow_policy


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train local neural shadow policy.")
    parser.add_argument("--dataset", default=str(DATASET_PATH))
    parser.add_argument("--model-out", default=str(DEFAULT_MODEL_PATH))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--min-samples", type=int, default=50)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    rows, corrupt = load_jsonl(args.dataset)
    report = train_shadow_policy(rows, model_out=args.model_out, report_out=args.report_out, min_samples=args.min_samples)
    report["dataset_path"] = args.dataset
    report["corrupt_dataset_lines"] = corrupt
    atomic_write_json(args.report_out, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
