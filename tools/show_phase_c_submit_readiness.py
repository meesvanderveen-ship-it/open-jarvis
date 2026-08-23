#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import BotConfig


def _read_jsonl_tail(path: Path, limit: int) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with path.open('r', encoding='utf-8') as f:
            lines = f.readlines()[-max(1, limit):]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    except Exception:
        return []
    return rows


def build_report(project_root: Path, sample: int = 100) -> Dict[str, Any]:
    cfg = BotConfig()
    config_ok = True
    config_error = None
    try:
        cfg.validate()
    except Exception as exc:
        config_ok = False
        config_error = str(exc)

    rows = _read_jsonl_tail(project_root / 'logs' / 'phase_c_live_submit.jsonl', sample)
    by_status = Counter(str(r.get('status') or 'unknown') for r in rows)
    attempted = sum(1 for r in rows if bool(r.get('live_submission_attempted')))
    submitted = sum(1 for r in rows if bool(r.get('live_order_submitted')))
    diagnostic = sum(1 for r in rows if bool(r.get('diagnostic')))
    dry_run = sum(1 for r in rows if bool(r.get('dry_run')))
    blockers = Counter()
    for r in rows:
        for reason in r.get('hard_block_reasons') or []:
            blockers[str(reason)] += 1

    return {
        'generated_at': None,
        'config_ok': config_ok,
        'config_error': config_error,
        'execution_mode': getattr(cfg, 'execution_mode', None),
        'enable_phase_c_live_small_limit_orders': getattr(cfg, 'enable_phase_c_live_small_limit_orders', False),
        'enable_live_limit_orders': getattr(cfg, 'enable_live_limit_orders', False),
        'enable_live_entry_orders': getattr(cfg, 'enable_live_entry_orders', False),
        'enable_live_exit_orders': getattr(cfg, 'enable_live_exit_orders', False),
        'enable_phase_c_live_submit_infrastructure': getattr(cfg, 'enable_phase_c_live_submit_infrastructure', True),
        'enable_phase_c_actual_coinbase_submit': getattr(cfg, 'enable_phase_c_actual_coinbase_submit', False),
        'phase_c_allowed_tickers': getattr(cfg, 'phase_c_allowed_tickers', []),
        'phase_c_max_order_quote': str(getattr(cfg, 'phase_c_max_order_quote', '')), 
        'phase_c_live_order_post_only': getattr(cfg, 'phase_c_live_order_post_only', True),
        'sample_size': len(rows),
        'by_status': dict(sorted(by_status.items())),
        'live_submission_attempted_count': attempted,
        'live_order_submitted_count': submitted,
        'diagnostic_count': diagnostic,
        'dry_run_count': dry_run,
        'hard_block_reasons_sample': dict(sorted(blockers.items())),
        'latest': rows[-5:],
        'safety_policy': 'C.2 is infrastructure/audit only. Actual Coinbase submit must remain disabled until a later explicit live phase.',
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Show Phase-C live-submit scaffold readiness.')
    parser.add_argument('--json', action='store_true', help='Print JSON report')
    parser.add_argument('--sample', type=int, default=100, help='Number of recent audit rows to inspect')
    args = parser.parse_args()
    report = build_report(PROJECT_ROOT, sample=args.sample)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
        return 0

    print('Phase-C live-submit scaffold readiness')
    print('======================================')
    for key in [
        'config_ok', 'execution_mode', 'enable_phase_c_live_small_limit_orders',
        'enable_live_limit_orders', 'enable_live_entry_orders', 'enable_live_exit_orders',
        'enable_phase_c_live_submit_infrastructure', 'enable_phase_c_actual_coinbase_submit',
        'phase_c_allowed_tickers', 'phase_c_max_order_quote', 'phase_c_live_order_post_only',
    ]:
        print(f'{key}: {report.get(key)}')
    if report.get('config_error'):
        print('config_error:', report['config_error'])
    print('\nAudit sample')
    print('sample_size:', report['sample_size'])
    print('by_status:', json.dumps(report['by_status'], sort_keys=True))
    print('live_submission_attempted_count:', report['live_submission_attempted_count'])
    print('live_order_submitted_count:', report['live_order_submitted_count'])
    print('diagnostic_count:', report['diagnostic_count'])
    print('dry_run_count:', report['dry_run_count'])
    print('hard_block_reasons_sample:', json.dumps(report['hard_block_reasons_sample'], sort_keys=True))
    if report.get('latest'):
        latest = report['latest'][-1]
        print('latest_status:', latest.get('status'))
        print('latest_diagnostic:', latest.get('diagnostic'))
        print('latest_dry_run:', latest.get('dry_run'))
        print('latest_live_submission_attempted:', latest.get('live_submission_attempted'))
        print('latest_live_order_submitted:', latest.get('live_order_submitted'))
    print('\nSafety: C.2 is read-only/disabled infrastructure; geen Coinbase submit zolang ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
