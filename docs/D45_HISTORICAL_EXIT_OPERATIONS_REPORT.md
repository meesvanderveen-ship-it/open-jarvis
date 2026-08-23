# D.45 Historical Exit Operations Report

## Purpose

`bot/phase_d45_historical_exit_operations_report.py` reconstructs the active BTC-USDC exit lifecycle from local files only. It is an audit/report layer for the current D.3/D.4 TP1 path and the next operator cycle.

CLI:

```bash
python3 tools/show_phase_d45_historical_exit_operations_report.py --json
```

The tool reads local order/position state and can optionally read `logs/order_events.jsonl` plus a fixture market mid. It never calls Coinbase, submits, cancels, replaces, reprices, applies lifecycle changes or writes trading state.

## Report Contents

The report answers:

- active replacement order identity and status
- old TP1 order identity and terminal status
- timeline from original TP1 to replacement TP1
- local coherence: exactly one open exit, coherent reservation, duplicate/oversell flags
- D.5 no-fill/stale metrics and target-distance band when market input is supplied
- trigger policy status
- next valid routes for open, fill, terminal and safety-drift evidence

## Current BTC-USDC Path

Expected coherent path:

1. Original TP1 SELL at `84800.00` was submitted under D.3.
2. D.4 controlled cancel-first reprice cancelled the old order.
3. Replacement TP1 SELL was submitted at `76000.00`.
4. The replacement is the active order while the operator waits for a valid trigger.

## Safety

The report is local-only and report-only:

- no Coinbase call
- no live action
- no cancel/replace/submit/reprice
- no lifecycle apply
- no trading-state write
- no service restart
- no learning-to-execution
