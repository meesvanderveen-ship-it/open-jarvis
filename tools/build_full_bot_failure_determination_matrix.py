#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.full_bot_failure_determination_matrix import (
    CONFIGURED_USDC_TICKERS,
    build_full_bot_failure_determination_matrix,
    load_json_file,
    load_latest_report,
    render_full_bot_failure_determination_markdown,
)


def _load_explicit_or_latest(root: Path, explicit: str, pattern: str) -> tuple[dict, Path | None]:
    if explicit:
        path = Path(explicit)
        return load_json_file(path), path
    return load_latest_report(root, pattern)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build report-only Full Bot all-ticker failure determination matrix.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--all-configured-tickers", action="store_true", help="Include all 18 configured USDC tickers.")
    parser.add_argument("--d6-report", default="")
    parser.add_argument("--orchestrator-report", default="")
    parser.add_argument("--adapter-report", default="")
    parser.add_argument("--post-review-adapter-report", default="")
    parser.add_argument("--review-report", default="")
    parser.add_argument("--fresh-evidence-report", default="")
    parser.add_argument("--open-orders", default="state/open_orders.json")
    parser.add_argument("--positions", default="state/positions.json")
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--markdown-out", required=True)
    args = parser.parse_args()

    root = Path(args.root)
    d6, d6_path = _load_explicit_or_latest(root, args.d6_report, "d6-multi-order-intent-preview-calibrated-*.json")
    orch, orch_path = _load_explicit_or_latest(root, args.orchestrator_report, "full-bot-orchestrator-*.json")
    adapter, adapter_path = _load_explicit_or_latest(root, args.adapter_report, "full-bot-maker-buy-live-adapter-*.json")
    post_adapter, post_adapter_path = _load_explicit_or_latest(root, args.post_review_adapter_report, "full-bot-maker-buy-live-adapter-post-review-*.json")
    review, review_path = _load_explicit_or_latest(root, args.review_report, "full-bot-near-miss-phase-c-review-*.json")
    evidence, evidence_path = _load_explicit_or_latest(root, args.fresh_evidence_report, "full-bot-fresh-phase-c-evidence-*.json")

    open_orders_path = root / args.open_orders
    positions_path = root / args.positions
    open_orders = load_json_file(open_orders_path)
    positions = load_json_file(positions_path)

    source_paths = [
        p
        for p in [
            d6_path,
            orch_path,
            adapter_path,
            post_adapter_path,
            review_path,
            evidence_path,
            open_orders_path,
            positions_path,
        ]
        if p is not None
    ]
    report = build_full_bot_failure_determination_matrix(
        d6_report=d6,
        orchestrator_report=orch,
        adapter_report=adapter,
        post_review_adapter_report=post_adapter,
        review_report=review,
        fresh_evidence_report=evidence,
        open_orders_state=open_orders,
        positions_state=positions,
        configured_tickers=CONFIGURED_USDC_TICKERS,
        source_paths=source_paths,
    )

    json_out = Path(args.json_out)
    md_out = Path(args.markdown_out)
    if not json_out.is_absolute():
        json_out = root / json_out
    if not md_out.is_absolute():
        md_out = root / md_out
    allowed_dir = (root / "reports" / "d6").resolve()
    for path in (json_out, md_out):
        resolved_parent = path.resolve().parent
        if resolved_parent != allowed_dir:
            raise SystemExit(f"Refusing to write outside reports/d6: {path}")
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_out.write_text(render_full_bot_failure_determination_markdown(report), encoding="utf-8")
    print(f"wrote_json={json_out}")
    print(f"wrote_markdown={md_out}")
    print(f"total_configured_tickers={report['summary']['total_configured_tickers']}")
    print(f"any_ticker_phase_c_ready_now={report['summary']['any_ticker_phase_c_ready_now']}")
    print(f"max_new_orders_per_cycle_hides_viable_candidates={report['summary']['max_new_orders_per_cycle_hides_viable_candidates']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
