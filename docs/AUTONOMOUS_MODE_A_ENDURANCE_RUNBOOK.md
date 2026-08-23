# Autonomous Mode A Endurance Runbook

Mode A is the bounded long-run mode: autonomous analysis, orderbook BUY, D3 limit SELL, D3 lifecycle polling and controlled stop-exit preview-only.

Current Mode A baseline, 2026-06-14:

- Approved profile: `sizing_only_20_100_conservative_v1`.
- Approved profile hash: `4db7716bbdda192b7eae9f962f27bb87273fc2ff3d50613b66c4ba75712bfb12`.
- Default quote remains `20.00` USDC; max entry/exit quote rails are `100.00` USDC.
- D2 thresholds remain conservative: expected net edge `0.0125`, reward/fee `3.0`, reward/risk `1.5`.
- Market orders are disabled unless separate Mode C is explicitly armed. Replication, bounded exploration, neural execution, direct learning-to-execution and automatic parameter mutation must remain disabled.
- Current local state baseline: `open_orders=0`, `open_d3_exit=0`, `open_positions=0`.
- Wait/passivity is acceptable when the market is weak; do not loosen entry or D2 criteria to force trades.

## Pre-Run

1. Check readiness:
   ```bash
   python3 tools/show_full_autonomous_run_readiness.py --json
   ```
2. Prepare the endurance run:
   ```bash
   python3 tools/prepare_autonomous_endurance_run.py --hours 24 --json
   ```
3. Inspect open D3 exits in the prepare output.
4. Confirm Mode B is disabled and stop-exit apply remains preview-only.
5. Confirm `ENABLE_AUTONOMOUS_STOP_EXIT_APPLY=false` unless a separate Mode B ACK is deliberately being tested. Mode A is not ready if autonomous stop-exit apply is enabled without the exact Mode B ACK.

## Start

Operator command:
```bash
sudo systemctl restart coinbase-bot.service
```

Monitor immediately:
```bash
python3 tools/show_autonomous_live_run_status.py --json
```

Follow logs:
```bash
journalctl -u coinbase-bot -f --no-pager -l
```

## During Run

Use status, not manual state edits:
```bash
python3 tools/show_autonomous_live_run_status.py --json
```

Stop the run for:

- duplicate open D3 exit;
- missing exchange order id on an open live order;
- lifecycle hook exception;
- repeated atomic/state-write error;
- process lock conflict;
- repeated Coinbase lookup failure;
- unexpected live cancel/replace/apply;
- more than configured max open orders;
- oversell or duplicate SELL signal;
- `run_health=critical`.

## After 6 Hours

```bash
python3 tools/write_autonomous_live_run_report.py --since-hours 6 --json-out reports/live_runs/live-run-6h.json
python3 tools/summarize_autonomous_run_next_steps.py --run-report reports/live_runs/live-run-6h.json --balanced-profile reports/live_learning/balanced-start-profile-candidate.json --json
```

## After 24 Hours

```bash
python3 tools/write_autonomous_live_run_report.py --since-hours 24 --json-out reports/live_runs/live-run-24h.json
python3 tools/summarize_autonomous_run_next_steps.py --run-report reports/live_runs/live-run-24h.json --balanced-profile reports/live_learning/balanced-start-profile-candidate.json --json
```

## Decisions

- Continue baseline when runtime is clean but evidence is sparse.
- Review conservative profile when missed-fill evidence exists without risk errors.
- Keep moderate profile for later review until evidence is stronger.
- Prepare Mode B only after clean D3/stop-exit evidence and a separate ACK.
- Prepare Mode C only for the POC market-order run with exact ACK and replication disabled.
- Stop and fix when lifecycle, atomic, process, duplicate or oversell evidence appears.

## Mode C Market Order POC

Mode C is separate from Mode A and Mode B. It allows market orders only when all three flags and the exact ACK are present:

```env
MARKET_ORDER_ENABLED=true
ENABLE_MARKET_ORDERS=true
ALLOW_MARKET_ORDERS=true
MODE_C_MARKET_ORDER_ACK=I_APPROVE_MARKET_ORDERS_FOR_POC_20_100_NO_REPLICATION
ENABLE_CONTROLLED_STOP_MARKET_EXITS=true
ENABLE_AUTONOMOUS_STOP_EXIT_CANCEL=true
ENABLE_AUTONOMOUS_STOP_EXIT_SUBMIT=true
ENABLE_AUTONOMOUS_STOP_EXIT_APPLY=true
MODE_B_CONTROLLED_STOP_EXIT_ACK=I_APPROVE_MODE_B_CONTROLLED_STOP_EXIT_APPLY
REPLICATION_ENABLED=false
REPLICATION_LIFECYCLE_ENABLED=false
REPLICATION_LIFECYCLE_HTTP_ENABLED=false
MIN_LIVE_ORDER_QUOTE_USDC=20.00
MAX_LIVE_ORDER_QUOTE_USDC=100.00
DEFAULT_QUOTE_SIZE_USDC=20.00
MAX_NOTIONAL_USD=100.00
MAX_NEW_ORDERS_PER_CYCLE=1
AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE=1
PHASE_C_MAX_NEW_ORDERS_PER_CYCLE=1
AUTONOMOUS_MAX_OPEN_ORDERS=3
PHASE_C_MAX_OPEN_ENTRY_ORDERS=3
MAX_OPEN_POSITIONS=3
PHASE_C43_LIFECYCLE_ALLOW_COINBASE_POLL=true
PHASE_C43_LIFECYCLE_APPLY_LOCAL=true
PHASE_C43_LIFECYCLE_BUILD_D2_PLAN=true
PHASE_C43_LIFECYCLE_PERSIST_D2_PLAN=true
PHASE_C43_LIFECYCLE_BUILD_D3_PREVIEW=true
NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED=false
LEARNING_TO_EXECUTION_ALLOWED=false
LIVE_LEARNING_ALLOWED=false
PARAMETER_CHANGE_ALLOWED=false
```

Market BUY rules: `approve_trade`, side `BUY`, concrete `trade_plan`, deterministic risk green, allowed ticker, quote `20.00-100.00`, no duplicate open order and no max-position/max-order breach.

Market SELL rules: existing bot-managed base only, never naked sell, never oversell, never duplicate D3/exit, and terminal Coinbase fill evidence before local apply.

Stop-exit relation: Mode B remains the primary controlled stop-exit apply governance. Mode C market flags do not by themselves allow autonomous stop-exit local apply; fill evidence and Mode B or explicit stop governance remain required.

Operator start sequence after editing `.env`:

```bash
python3 tools/show_full_autonomous_run_readiness.py --json
sudo systemctl restart coinbase-bot.service
python3 tools/show_autonomous_live_run_status.py --json
```

Rollback:

```bash
# edit .env back to:
MARKET_ORDER_ENABLED=false
ENABLE_MARKET_ORDERS=false
ALLOW_MARKET_ORDERS=false
MODE_C_MARKET_ORDER_ACK=
ENABLE_AUTONOMOUS_STOP_EXIT_CANCEL=false
ENABLE_AUTONOMOUS_STOP_EXIT_SUBMIT=false
ENABLE_AUTONOMOUS_STOP_EXIT_APPLY=false
MODE_B_CONTROLLED_STOP_EXIT_ACK=
REPLICATION_ENABLED=false
REPLICATION_LIFECYCLE_ENABLED=false
REPLICATION_LIFECYCLE_HTTP_ENABLED=false

sudo systemctl restart coinbase-bot.service
python3 tools/show_full_autonomous_run_readiness.py --json
```

## Hard Prohibitions

- No manual duplicate SELL.
- No Mode B flags without exact ACK.
- No Mode C market flags without exact ACK and replication disabled.
- No `MODE_B_CONTROLLED_STOP_EXIT_ACK` unless the operator is explicitly activating Mode B.
- No profile activation without hash ACK.
- No `.env` mutation during observation.
- No production state repair during observation.
