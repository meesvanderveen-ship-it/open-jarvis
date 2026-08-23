#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.neural_feature_schema import DATASET_PATH
from bot.neural_shadow_policy import DEFAULT_EVAL_PATH, DEFAULT_MODEL_PATH, evaluate_shadow_policy, load_jsonl


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate local neural shadow policy.")
    parser.add_argument("--model", default=str(DEFAULT_MODEL_PATH))
    parser.add_argument("--dataset", default=str(DATASET_PATH))
    parser.add_argument("--json-out", default=str(DEFAULT_EVAL_PATH))
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    rows, corrupt = load_jsonl(args.dataset)
    report = evaluate_shadow_policy(rows, model_path=args.model, json_out=args.json_out)
    report["corrupt_dataset_lines"] = corrupt
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
