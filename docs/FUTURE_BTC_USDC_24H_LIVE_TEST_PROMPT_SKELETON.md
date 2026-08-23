# Future BTC-USDC 24h Live-Test Prompt Skeleton

Status: template only. Do not execute without replacing every placeholder and providing the exact ACKs below.

## Scope

- product_id: `BTC-USDC`
- live_window: `24h`
- max_notional_usdc: `<MAX_NOTIONAL_USDC>`
- live_start_time: `<LIVE_START_TIME_UTC>`
- live_end_time: `<LIVE_END_TIME_UTC>`
- allowed_order_types: `<ALLOWED_ORDER_TYPES>`
- allowed_sides: `<ALLOWED_SIDE_OR_SIDES>`
- all_ticker_enabled: `false`
- non_btc_tickers_enabled: `false`
- parameter_mutation_allowed: `false`
- learning_to_execution_enabled: `false`
- normal_backtest_release: `false`

## Required Fresh Preflight Evidence

- fresh_preflight_report_ids: `<FRESH_PREFLIGHT_REPORT_IDS>`
- generated_operator_pack_path: `<REPORTS_D6_OPERATOR_PACK_JSON_OR_MD>`
- startup_diagnostic_status: `<STARTUP_DIAGNOSTIC_STATUS>`
- monitor_since_utc: `<OPERATOR_START_UTC_FOR_MONITOR>`
- post_run_evidence_expected_paths: `<REPORTS_LIVE_POST_RUN_JSON_MD_PATHS>`
- c4_d1_branch_map_expected_paths: `<REPORTS_D6_C4_D1_BRANCH_MAP_JSON_MD_PATHS>`
- product_rules_report_id: `<PRODUCT_RULES_REPORT_ID>`
- balance_open_order_report_id: `<BALANCE_OPEN_ORDER_REPORT_ID>`
- local_coinbase_coherence_report_id: `<LOCAL_COINBASE_COHERENCE_REPORT_ID>`
- safety_validation_report_id: `<SAFETY_VALIDATION_REPORT_ID>`
- state_open_orders_sha256: `<STATE_OPEN_ORDERS_SHA256>`
- state_positions_sha256: `<STATE_POSITIONS_SHA256>`

## Operator Command Sequence

A. Confirm service/process scope: Codex does not start the process; any operator wrapper must preserve BTC-USDC-only tiny scope.

B. Fresh BTC-USDC tiny preflight:

```bash
tools/operator_btc_usdc_tiny_env.sh .venv/bin/python tools/show_btc_usdc_tiny_live_preflight.py \
  --json-out reports/d6/btc-usdc-tiny-live-preflight-$(date -u +%Y%m%d).json \
  --markdown-out reports/d6/btc-usdc-tiny-live-preflight-$(date -u +%Y%m%d).md
```

C. Startup diagnostic:

```bash
tools/operator_btc_usdc_tiny_env.sh .venv/bin/python run_trader_loop.py --startup-diagnostic
```

D. Baseline state hashes:

```bash
sha256sum state/open_orders.json state/positions.json
```

E. Exact operator ACK live-start command:

```bash
BTC_USDC_TINY_ACTUAL_SUBMIT_ACK=I_APPROVE_BTC_USDC_TINY_24H_ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT_MAX_10_USDC \
  tools/operator_btc_usdc_tiny_env.sh .venv/bin/python run_trader_loop.py
```

F. During-run monitor:

```bash
python3 tools/show_btc_usdc_24h_live_monitor.py --json --since-utc <OPERATOR_START_UTC> \
  --baseline-open-orders-hash <PRE_START_OPEN_ORDERS_SHA256> \
  --baseline-positions-hash <PRE_START_POSITIONS_SHA256>
```

G. Stop rules: `OK` continues, `WATCH` requires review, `STOP_NOW` stops the operator run and forbids apply/repair/exit without a separate exact ACK.

H. Post-run evidence pack:

```bash
python3 tools/build_btc_usdc_24h_post_run_evidence_pack.py \
  --start-utc <OPERATOR_START_UTC> \
  --stop-utc <OPERATOR_STOP_UTC> \
  --baseline-open-orders-hash <PRE_START_OPEN_ORDERS_SHA256> \
  --baseline-positions-hash <PRE_START_POSITIONS_SHA256> \
  --json-out reports/live/btc-usdc-24h-evidence-$(date -u +%Y%m%d).json \
  --markdown-out reports/live/btc-usdc-24h-evidence-$(date -u +%Y%m%d).md
```

I. C4/D1 branch map:

```bash
python3 tools/build_c4_d1_handoff_branch_map.py \
  --json-out reports/d6/c4-d1-handoff-branch-map-$(date -u +%Y%m%d).json \
  --markdown-out reports/d6/c4-d1-handoff-branch-map-$(date -u +%Y%m%d).md
```

J. Boundaries: fill-to-position apply, lifecycle apply, local repair, live D3 exit submit, cancel/replace/reprice and Codex Coinbase read-only poll each require separate exact ACK.

## Stop Thresholds

- max_notional_usdc: `<MAX_NOTIONAL_USDC>`
- max_open_orders: `<MAX_OPEN_ORDERS>`
- provider_error_threshold: `<PROVIDER_ERROR_THRESHOLD>`
- coinbase_api_error_threshold: `<COINBASE_API_ERROR_THRESHOLD>`
- invalid_json_threshold: `<INVALID_JSON_THRESHOLD>`
- drawdown_or_loss_threshold: `<DRAWDOWN_OR_LOSS_THRESHOLD>`
- manual_stop_contact: `<MANUAL_STOP_CONTACT_OR_CHANNEL>`

## Telemetry

- telemetry_cadence: `<TELEMETRY_CADENCE>`
- checkpoint_schedule: `<CHECKPOINT_SCHEDULE>`
- evidence_output_paths: `<EVIDENCE_OUTPUT_PATHS>`

## Exact ACKs

Required before any 24h live-test start:

`I_APPROVE_BTC_USDC_ONLY_24H_LIVE_TEST_WITH_EXACT_SCOPE_MAX_NOTIONAL_AND_PREFLIGHT_PASS`

Required before any live submit:

`I_APPROVE_SINGLE_BTC_USDC_LIVE_SUBMIT_FOR_24H_TEST_WITH_EXACT_ORDER_PARAMS`

Required before lifecycle apply from fill or terminal evidence:

`I_APPROVE_LIFECYCLE_APPLY_FOR_SPECIFIC_BTC_USDC_EVIDENCE`

Required before C4.5 fill-to-position apply:

`I_UNDERSTAND_AND_APPROVE_C45_FILL_TO_POSITION_APPLY`

Required before cancel or reprice of a specific order:

`I_APPROVE_BTC_USDC_CANCEL_OR_REPRICE_FOR_SPECIFIC_ORDER_ID`

Required before any config or parameter mutation:

`I_APPROVE_EXPLICIT_CONFIG_OR_PARAMETER_MUTATION_FOR_SPECIFIC_DIFF`

## Hard Boundaries

- No live submit unless the specific submit ACK is present.
- No cancel, replace or reprice unless the specific order-id ACK is present.
- No lifecycle apply unless specific evidence and ACK are present.
- No fill-to-position apply unless exact fill evidence and the C4.5 fill apply ACK are present.
- No `state/` write unless separately ACKed and evidence-backed.
- D2/D3 preview is not live exit permission; D3 preview must keep `submit_live=False` and does not authorize a SELL.
- No `.env`, config, risk, strategy, prompt or parameter mutation unless separately ACKed.
- No learning-to-execution.
- No service restart without separate approval.
- No all-ticker expansion.

## Operator Fill-In Checklist

- Replace every `<PLACEHOLDER>`.
- Attach fresh preflight report IDs.
- Attach exact state hashes from immediately before the proposed start.
- Confirm max notional.
- Confirm start and end time.
- Confirm telemetry cadence and stop thresholds.
- Provide only the ACKs intended for the next bounded action.
