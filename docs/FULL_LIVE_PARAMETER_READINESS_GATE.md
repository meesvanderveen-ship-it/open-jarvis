# Full Live Parameter Readiness & Start Gate v1

This gate is report-only. It reads `.env`, state files and latest Full Bot D.6 reports, then decides whether a live maker-BUY test can proceed.

It must not mutate `.env`, start the bot, submit/cancel/replace orders, call Coinbase write endpoints, enable SELL, enable market orders, enable exits, enable replication, enable learning-to-execution or write trading state.

## Verdicts

- `ready_for_env_update_only`: reserved for a future explicit parameter-approval sprint.
- `ready_for_process_local_live_start`: environment and evidence are clean, but actual submit ACK is absent.
- `ready_for_ack_gated_maker_buy_actual_submit`: exact ACK is present and every Phase-C/safety guard is clean.
- `blocked_by_missing_fresh_judge_and_risk`: selected candidates still lack fresh BUY judge approval or deterministic live-risk approval.
- `blocked_by_missing_fresh_candidate_refresh`: no Phase-C-ready candidate exists and candidates need refresh.
- `blocked_by_env_mismatch`: a required disabled surface is enabled or required env values are mismatched.
- `blocked_by_safety_gap`: state or lifecycle safety is not clean.
- `unsafe_to_start`: SELL, market, replication, learning-to-execution or another dangerous surface is enabled.

## Current Policy

Use process-local overrides for the full max-5/max-20 maker-BUY test until a separate prompt approves permanent `.env` edits. Actual submit remains ACK-gated with:

`I_APPROVE_FULL_BOT_MAKER_BUY_LIVE_MAX_5_ORDERS_MAX_20_USDC_NO_SELL_NO_MARKET`

SELL, exits, D3 actual exit submit, market orders, replication, live learning, learning-to-execution and parameter mutation stay disabled.

## Full Workflow Live Max3x20 Addendum

The full workflow live max3x20 BUY-and-SELL path is master-only. It uses this exact ACK:

`I_APPROVE_FULL_WORKFLOW_LIVE_MAX_3_ORDERS_MAX_20_USDC_BUY_AND_SELL_NO_MARKET_NO_REPLICATION`

Hard requirements for that path:

- `REPLICATION_ENABLED=false`
- `MARKET_ORDER_ENABLED=false`, `ENABLE_MARKET_ORDERS=false`, `ALLOW_MARKET_ORDERS=false`
- learning-to-execution, live learning and parameter mutation remain false
- reports must expose `replication_enabled=false`, `replication_publish_allowed=false` and `follower_lifecycle_enabled=false`
- any replication publish attempt during the run must remain skipped with `reason=replication_disabled`

The exact ACK must never enable replication. `BotConfig.validate()` and function-preservation audit must fail closed if full workflow live mode is paired with `REPLICATION_ENABLED=true`.

## Report Command

```bash
python3 tools/build_full_live_parameter_readiness_gate.py \
  --json-out reports/d6/full-live-parameter-readiness-gate-$(date -u +%Y%m%d).json \
  --markdown-out reports/d6/full-live-parameter-readiness-gate-$(date -u +%Y%m%d).md
```
