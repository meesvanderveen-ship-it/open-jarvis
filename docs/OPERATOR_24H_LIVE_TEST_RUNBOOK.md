# Operator 24h Live Test Runbook

Status: operator-start workflow only. This document does not authorize a live run.

## Scope

- Proven product: `BTC-USDC`.
- Preferred first live-test scope: `BTC-USDC` only.
- Tiny budget: every effective order/notional cap must be `<=10` USDC.
- Effective live scope must be `BTC-USDC` only: no all-ticker scope.
- `max_new_orders_per_cycle=1` and effective max open orders `=1`.
- Live exits and learning-to-execution must remain disabled.
- `ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=true` is allowed only after a separate exact ACK.
- All-ticker live trading remains blocked.
- Learning-to-execution remains blocked.
- Parameter, strategy, risk, prompt and `.env` mutation remain blocked unless a future prompt approves the exact diff.
- D.6 multi-order intent preview is report-only and is not part of this live-start path. It may show future BUY/SELL/market intent structure, but it does not authorize live submit, market orders, SELL execution or wider all-ticker scope.
- For the separate full workflow live max3x20 BUY-and-SELL test, replication/follower must stay off: `REPLICATION_ENABLED=false`, `replication_publish_allowed=false`, `follower_lifecycle_enabled=false`, and any replication publish evidence must be `skipped=True` with `reason=replication_disabled`.

Codex must not start the 24h process, restart a service, call Coinbase, submit, cancel, replace, reprice, lifecycle-apply, repair local state or mutate config during this workflow-preparation task.

## Operator Sequence

A. Confirm service/process scope.
B. Run fresh BTC-USDC tiny preflight.
C. Run startup diagnostic.
D. Capture baseline state hashes.
E. Use the exact operator ACK live-start command only after fresh pass.
F. Run the during-run monitor with `--since-utc`.
G. Follow `OK` / `WATCH` / `STOP_NOW` stop rules.
H. Build the post-run evidence pack with explicit start/stop UTC.
I. Build the C4/D1 branch map and select Branch A-G.
J. Keep fill apply, lifecycle apply, local repair, live D3 exit submit, cancel/replace/reprice and Codex Coinbase read-only poll behind separate exact ACKs.

## A. Before-Run Preflight

Run from `/root/apps/Crypto/coinbase_bot`:

```bash
.venv/bin/python tools/build_live_operator_runbook_pack.py \
  --json-out reports/d6/operator-24h-live-test-pack-$(date -u +%Y%m%d).json \
  --markdown-out reports/d6/operator-24h-live-test-pack-$(date -u +%Y%m%d).md

tools/operator_btc_usdc_tiny_env.sh .venv/bin/python tools/show_btc_usdc_tiny_live_preflight.py \
  --json-out reports/d6/btc-usdc-tiny-live-preflight-$(date -u +%Y%m%d).json \
  --markdown-out reports/d6/btc-usdc-tiny-live-preflight-$(date -u +%Y%m%d).md

tools/operator_btc_usdc_tiny_env.sh .venv/bin/python run_trader_loop.py --startup-diagnostic

python3 tools/show_open_orders.py --open-only --json --limit 20
python3 tools/show_function_preservation_audit.py --fail-on-review
python3 tools/show_phase_d3_controlled_live_exits.py --ticker BTC-USDC --json
sha256sum state/open_orders.json state/positions.json
python3 - <<'PY'
from bot.config import BotConfig
c = BotConfig()
c.validate()
print(c.to_dict())
PY
```

Must pass:

- `open_orders=0`.
- `open_d3_exit=0`.
- `tools/show_btc_usdc_tiny_live_preflight.py` returns `status=pass_btc_usdc_tiny_preflight`.
- `run_trader_loop.py --startup-diagnostic` returns `effective_runtime_tickers=["BTC-USDC"]`, `phase_c_allowed_tickers=["BTC-USDC"]`, `tiny_mode_active=true`, `fail_closed=false`, `no_llm_call=true`, `no_coinbase_call=true`, and `state_write_performed=false`.
- function audit reports `ok_observe_only`, or only exact separately ACKed live flags are enabled.
- effective live scope is `BTC-USDC` only for `allowed_tickers` and `phase_c_allowed_tickers`.
- `default_quote_size_usdc`, `max_notional_usd`, `phase_c_max_order_quote` and `autonomous_max_order_quote` are all `<=10` USDC.
- `max_new_orders_per_cycle`, `phase_c_max_new_orders_per_cycle` and `autonomous_max_new_orders_per_cycle` are all `1`.
- `max_open_positions`, `phase_c_max_open_entry_orders` and `autonomous_max_open_orders` are all `1`.
- `enable_live_exit_orders=false`, `enable_phase_d3_actual_exit_submit=false`, `autonomous_allow_exits=false`.
- learning-to-execution is disabled.
- pre-ACK preflight keeps `enable_phase_c_actual_coinbase_submit=false`.
- no parameter/config mutation is pending.
- any `reports/d6/d6-multi-order-intent-preview-*.json` artifact is treated as advisory preview only and must not be wired into live execution during this runbook.
- state hashes are captured before start.

Block the run if any open order, active D.3 exit, duplicate/oversell warning, non-BTC live scope, excessive notional, learning-to-execution, parameter mutation or unexpected hash drift appears.

State hygiene note: `reports/d6/state-hygiene-cleanup-preview-20260609.json` classifies the stale BTC-USDC denormalized reservation as `WATCH`, not `STOP_NOW`. This preview is not required to be applied before a live-start review unless a fresh report says `STOP_NOW`; any actual state repair still requires a separate exact ACK.

Local regression harness note: `python3 tools/run_safe_regression_harness.py --markdown` bundles local open-order checks, function audit, state hashes and report references. It is not a live preflight, does not call Coinbase, does not write trading state and does not authorize live trading. Fresh preflight, live start, state cleanup apply, lifecycle apply and any SELL still require separate exact ACKs.

## A.1 Operator Override Wrapper

Do not edit `.env` for this test unless a future prompt approves an exact diff.

Use `tools/operator_btc_usdc_tiny_env.sh` to create the temporary BTC-USDC-only tiny-budget process environment. The wrapper:

- loads `.env` via `python-dotenv` instead of shell-sourcing it;
- exports BTC-USDC-only overrides after sourcing `.env`;
- sets `BOT_CONFIG_SKIP_DOTENV=true` so `BotConfig` cannot overwrite those overrides from `.env`;
- marks `BTC_USDC_TINY_WRAPPER_MODE=true` for the runtime startup guard;
- forces pre-ACK `ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false`;
- does not call Coinbase, submit, cancel, replace, write state or start the bot unless the operator supplies a command.

Pre-ACK config-only preflight:

```bash
tools/operator_btc_usdc_tiny_env.sh .venv/bin/python tools/show_btc_usdc_tiny_live_preflight.py
tools/operator_btc_usdc_tiny_env.sh .venv/bin/python run_trader_loop.py --startup-diagnostic
```

The exact ACK string for a later armed-start preflight is:

```text
I_APPROVE_BTC_USDC_TINY_24H_ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT_MAX_10_USDC
```

After that separate ACK only, the operator may set `BTC_USDC_TINY_ACTUAL_SUBMIT_ACK` for the wrapper and run the armed-start preflight:

```bash
BTC_USDC_TINY_ACTUAL_SUBMIT_ACK=I_APPROVE_BTC_USDC_TINY_24H_ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT_MAX_10_USDC \
  tools/operator_btc_usdc_tiny_env.sh .venv/bin/python tools/show_btc_usdc_tiny_live_preflight.py \
  --actual-submit-ack I_APPROVE_BTC_USDC_TINY_24H_ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT_MAX_10_USDC \
  --require-actual-submit-enabled
```

## B. Start

Codex does not start the run.

Operator start option after a fresh preflight pass and separate exact live-start ACK:

```bash
cd /root/apps/Crypto/coinbase_bot
BTC_USDC_TINY_ACTUAL_SUBMIT_ACK=I_APPROVE_BTC_USDC_TINY_24H_ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT_MAX_10_USDC \
  tools/operator_btc_usdc_tiny_env.sh .venv/bin/python run_trader_loop.py
```

Before using any external start bash, verify it does not widen tickers, budget, submit flags, exit flags, learning flags or runtime config beyond the exact ACKed scope.

## C. During-Run Monitoring

Suggested cadence: watch closely for the first 15 minutes, then check at least every 15 minutes and whenever an alert/log anomaly appears.

Preferred local read-only monitor:

```bash
python3 tools/show_btc_usdc_24h_live_monitor.py \
  --json \
  --since-utc <OPERATOR_START_UTC> \
  --baseline-open-orders-hash <PRE_START_OPEN_ORDERS_SHA256> \
  --baseline-positions-hash <PRE_START_POSITIONS_SHA256>
```

Compact view:

```bash
python3 tools/show_btc_usdc_24h_live_monitor.py \
  --markdown \
  --since-utc <OPERATOR_START_UTC> \
  --baseline-open-orders-hash <PRE_START_OPEN_ORDERS_SHA256> \
  --baseline-positions-hash <PRE_START_POSITIONS_SHA256>
```

Classification:

- `OK`: local evidence remains inside the BTC-USDC tiny scope; continue monitoring.
- `WATCH`: review the listed reason before continuing, for example no active run process or an isolated provider/runtime warning.
- `STOP_NOW`: stop the operator run now; do not apply repair/lifecycle actions without a separate exact ACK.

The monitor is local/read-only: it reads logs, state, `.env` flag snapshots and process evidence only. It does not call Coinbase, submit, cancel, replace, reprice, write state, apply lifecycle, repair local state, restart services or mutate config.

Use `--since-utc <OPERATOR_START_UTC>` for a new run so older log evidence, including previous stopped all-ticker misstarts, is not mixed into the active 24h window.

The JSON report is the canonical evidence pack. The Markdown view is a compact operator view and includes process status, last cycle/heartbeat, open orders, D.3 exits, loop errors/tracebacks, LLM corrupt outputs, provider errors, lifecycle hook status, replication evidence and current state hashes.

After a service restart in any approved full workflow live max3x20 test, check local service logs/reports for replication evidence. The expected result is still `REPLICATION_ENABLED=false`, `replication_publish_allowed=false`, `follower_lifecycle_enabled=false`, and replication publish rows skipped with `reason=replication_disabled`. Any enabled, posted, published, follower lifecycle or server-2 publish evidence is a `STOP_NOW` condition.

Legacy manual checks remain useful for detailed inspection:

```bash
tail -n 120 logs/loop.log
tail -n 80 logs/cycle_summary.jsonl
tail -n 80 logs/heartbeat_summary.jsonl
python3 tools/show_open_orders.py --open-only --json --limit 20
python3 tools/show_function_preservation_audit.py --fail-on-review
```

Danger conditions:

- non-`BTC-USDC` live order or decision.
- notional exceeds the exact ACKed cap.
- second open order, duplicate order or oversell warning.
- unexpected SELL/exit without a managed BTC-USDC position.
- traceback, retry storm or repeated provider/runtime failure.
- state hash drift without matching order/lifecycle evidence.
- learning, ranking approval or parameter mutation appears.
- monitor classification is `STOP_NOW`.

## D. Stop

Normal stop:

- If run in foreground: `Ctrl+C`.
- If an operator-maintained bash/service wrapper is used: use that wrapper's normal stop command.

Avoid abrupt kill unless the process ignores normal stop or dangerous action is imminent.

After stop:

```bash
sha256sum state/open_orders.json state/positions.json
python3 tools/show_open_orders.py --open-only --json --limit 50
python3 tools/show_function_preservation_audit.py --fail-on-review
python3 tools/show_phase_d3_controlled_live_exits.py --ticker BTC-USDC --json
```

## E. Post-Run Evidence Collection

Collect:

```bash
python3 tools/build_btc_usdc_24h_post_run_evidence_pack.py \
  --start-utc <OPERATOR_START_UTC> \
  --stop-utc <OPERATOR_STOP_UTC> \
  --baseline-open-orders-hash <PRE_START_OPEN_ORDERS_SHA256> \
  --baseline-positions-hash <PRE_START_POSITIONS_SHA256> \
  --json-out reports/live/btc-usdc-24h-evidence-$(date -u +%Y%m%d).json \
  --markdown-out reports/live/btc-usdc-24h-evidence-$(date -u +%Y%m%d).md

tail -n 200 logs/loop.log
tail -n 120 logs/cycle_summary.jsonl
tail -n 120 logs/heartbeat_summary.jsonl
tail -n 120 logs/loop_errors.jsonl 2>/dev/null || true
python3 tools/show_execution_outcomes.py --json 2>/dev/null || python3 tools/show_execution_outcomes.py
python3 tools/show_phase_d5_execution_metrics.py --json 2>/dev/null || python3 tools/show_phase_d5_execution_metrics.py
```

Paste back to Codex:

- exact start and stop UTC timestamps.
- generated operator pack paths.
- before and after state hashes.
- recent loop, cycle and heartbeat log tails.
- any `loop_errors.jsonl` entries.
- Coinbase UI/export order and fill evidence if the operator gathered it under a separate ACK.
- manual stop reason, if any.

Use exact UTC timestamps from the operator-started process. `--start-utc` should be the first timestamp at or just before the approved BTC-USDC tiny run started; `--stop-utc` should be the timestamp at or just after the operator stopped it. This prevents old historical evidence, including earlier all-ticker misstarts, from polluting the post-run pack.

Post-run pack status:

- `OK`: local evidence inside the selected window appears BTC-USDC-only and clean. Archive the pack and wait for the next operator decision.
- `WATCH`: evidence is incomplete or contains isolated warnings. Review reasons before any next live step.
- `STOP_NOW`: the selected window contains hard-stop evidence. Do not repair, lifecycle-apply, cancel, fill-reconcile, restart or resume without a separate exact ACK.

The post-run pack is local/read-only. It reads logs, local state and `.env` flag snapshots only; it does not call Coinbase, submit/cancel/replace/reprice, write trading state, apply lifecycle, repair local state, restart services or mutate config. The only writes are the requested evidence reports under `reports/live/`.

## F. C4/D1 Handoff Branch Map

After post-run evidence collection, build the read-only C4/D1 handoff map:

```bash
python3 tools/build_c4_d1_handoff_branch_map.py \
  --json-out reports/d6/c4-d1-handoff-branch-map-$(date -u +%Y%m%d).json \
  --markdown-out reports/d6/c4-d1-handoff-branch-map-$(date -u +%Y%m%d).md
```

Use the post-run evidence window first. The branch map is a static operator map plus current local-state summary; by default it ignores old terminal C4 history so historical rejected/cancelled/filled rows do not pollute a new run. If the operator is reviewing a fresh terminal filled C4 row from the selected run, use the post-run pack and then run the branch-map tool with `--include-terminal-c4-handoff` for that explicit evidence review.

Branch decisions:

- Branch A, no order submitted: archive evidence. No state apply, lifecycle apply, D2/D3 action or live exit.
- Branch B, order submitted but still open: keep monitoring or collect operator-side Coinbase UI/export evidence. Codex Coinbase read-only poll requires separate ACK. No local fill apply or D2/D3 position action.
- Branch C, rejected/submit rejected: inspect the rejection cause. No position creation, no lifecycle apply and no retry without separate live-submit ACK.
- Branch D, cancelled/terminal without fill: archive no-fill evidence. No D1 position transition, D2 plan or D3 action.
- Branch E, partial fill: collect exact filled base/quote/price/fee evidence. Fill-to-position preview is allowed; actual local apply requires exact `I_UNDERSTAND_AND_APPROVE_C45_FILL_TO_POSITION_APPLY`.
- Branch F, full fill: collect exact filled base/quote/price/fee/settled evidence. C4.5/D1 fill-to-position preview comes first; actual position creation requires exact `I_UNDERSTAND_AND_APPROVE_C45_FILL_TO_POSITION_APPLY`. D2 plan and D3 preview remain non-live.
- Branch G, inconsistent evidence: `STOP_NOW`. Do not repair, lifecycle-apply, cancel, fill-reconcile, reprice or submit exits without a separate exact ACK.

ACK boundaries that remain separate:

- fill-to-position apply;
- lifecycle apply;
- local repair;
- live D3 exit submit;
- cancel/replace/reprice;
- Codex Coinbase read-only poll.

D2/D3 preview is not live exit permission. A D3 preview must keep `submit_live=False` and does not authorize a SELL.

## All-Ticker Readiness Note

`reports/d6/all-ticker-readiness-gate-20260609.*` is local/report-only. BTC-USDC tiny-run readiness is separate from all-ticker readiness; `all_ticker_ready=false` and `all_ticker_live_allowed_now=false`. The gate does not call Coinbase, fetch market data, write trading state, mutate parameters, enable replication or authorize live trading. All-ticker live requires a separate exact ACK after product rules, data coverage, lifecycle evidence and operator scope are proven for every ticker.

## Full Bot Maker BUY Adapter Note

`reports/d6/full-bot-maker-buy-live-adapter-YYYYMMDD.*` is the ACK-gated bridge
from Full Bot Orchestrator entry candidates into the existing Phase-C maker BUY
path. The preview command is report-only and must be run before any actual
submit review:

```bash
python3 tools/build_full_bot_maker_buy_live_adapter_report.py \
  --orchestrator-report reports/d6/full-bot-orchestrator-$(date -u +%Y%m%d).json \
  --json-out reports/d6/full-bot-maker-buy-live-adapter-$(date -u +%Y%m%d).json \
  --markdown-out reports/d6/full-bot-maker-buy-live-adapter-$(date -u +%Y%m%d).md
```

The only future actual-submit ACK for this adapter is:

```text
I_APPROVE_FULL_BOT_MAKER_BUY_LIVE_MAX_5_ORDERS_MAX_20_USDC_NO_SELL_NO_MARKET
```

Actual submit, if separately approved later, is BUY-only, maker/limit-only,
post-only, max 20 USDC per order, max two new orders per cycle, max five open
orders total, max one open order per ticker and max 100 USDC reserved BUY quote.
It must still pass Phase-C guards. The adapter does not authorize SELL, market
orders, live exits, D3 actual exit submit, replication, learning-to-execution or
parameter mutation.

## Follower Receiver/API Note

`reports/d6/follower-receiver-api-audit-20260609.*` is local/report-only. It does not send HTTP to a follower, enable replication, enable follower live, call Coinbase or write trading state. Follower receiver/API code was not accessible from the checked local paths, so `follower_ready_for_live=false`, `follower_buy_ready=false`, `follower_sell_ready=false` and `lifecycle_parity_ready=false`. The master BTC-USDC tiny run path does not require follower live; any follower BUY, SELL or lifecycle apply path requires a separate exact ACK and audited receiver/API behavior first.

## Selected-Test And Workflow Parity Note

`python3 tools/run_safe_regression_harness.py --include-selected-tests` runs only a fixed local allowlist of cheap report/readiness tests. It does not accept arbitrary commands, is not a live preflight, does not call Coinbase or HTTP endpoints, does not write trading state and does not authorize live trading. `reports/d6/main-workflow-parity-report-20260609.*` separates the older multi-ticker analysis/decision workflow from the newer C4/D1/D2/D3/D4/D5 lifecycle/orderbook flow: non-BTC tickers are not nonexistent, but they are not yet proven through the newer lifecycle path. BTC-USDC remains the controlled tiny scope; all-ticker live, learning-to-execution and parameter changes remain disabled until separate governance and exact ACK.

## Multi-Ticker Paper Replay Note

`reports/d6/multi-ticker-paper-lifecycle-replay-20260609.*` is report-only and paper-only. It now consumes the product-rule fixture/evidence cache and maps all configured tickers through paper C4/D1/D2/D3/D4/D5 scenario labels without submit/cancel/replace, Coinbase calls, market-data fetches, HTTP calls, lifecycle apply, state writes, parameter mutation or learning-to-execution. Fixture-backed paper replay is not live product-rule readiness and does not authorize all-ticker live. BTC-USDC remains the controlled tiny-live scope after fresh preflight and exact ACK; non-BTC fixture evidence remains paper-only and requires fresh live/cached product-rule proof before live-scope review.

## Product-Rule Evidence Cache Note

`reports/d6/per-ticker-product-rule-evidence-cache-20260609.*` is local/report-only. It does not fetch Coinbase product rules, call Coinbase, fetch market data, send HTTP, write trading state, mutate parameters or authorize all-ticker live. BTC-USDC has local product-rule evidence from historical read-only reports, but still needs fresh preflight and exact ACK before any tiny-live start. Non-BTC tickers remain paper/lifecycle candidates only until local product-rule/min-size/increment evidence is collected and reviewed.

## Product-Rule Fixture Evidence Note

`reports/d6/product-rule-fixture-evidence-20260609.*` is local/report-only and fixture-based for the 17 non-BTC tickers. The fixtures can support paper lifecycle replay and backlearning constraint labels, but they are not live Coinbase product-rule proof, do not replace a fresh Coinbase product-rule preflight, do not authorize all-ticker live and do not authorize parameter changes. BTC-USDC remains the only controlled tiny-live scope after fresh preflight and exact ACK.

## D6 Backlearning Evidence Plan Note

`reports/d6/d6-backlearning-parameter-evidence-plan-20260609.*` is human-review/backlearning-only. It does not optimize, rank strategies for live use, propose parameter values, mutate parameters, enable live learning, connect learning-to-execution, call Coinbase, fetch market data, send HTTP or write trading state. It can guide future evidence review only; any parameter review, parameter change, live learning or learning-to-execution bridge requires separate governance and exact ACK.

## D6 Human-Review Decision Pack Note

`reports/d6/d6-human-review-decision-pack-20260609.*` is human-review decisioning only. It classifies evidence areas for review, labels-only use, insufficient evidence, blocked status or ACK-gated scope. It does not propose parameter values, approve parameter review, mutate parameters, optimize, rank strategies for live use, enable learning-to-execution, enable live learning, call Coinbase, fetch market data, send HTTP or write trading state.

## D6 Acceptance / Label Export / Decision Map Note

`reports/d6/d6-acceptance-policy-20260609.*`, `reports/d6/d6-backlearning-label-export-pack-20260609.*` and `reports/d6/roadmap-readiness-decision-map-20260609.*` are local/report-only governance artifacts. They define evidence sufficiency policy, export labels for offline review and map future route blockers. They do not train, optimize, rank strategies for live use, propose parameter values, approve parameter review, mutate parameters, enable learning-to-execution, enable live learning, call Coinbase, fetch market data, send HTTP, write trading state or authorize live trading.

## Controlled Learning Governance Note

`reports/d6/controlled-learning-governance-20260609.*` is governance-only and report-only. It defines future learning stages and ACK boundaries, but the current maximum allowed learning stage is `acceptance_policy_ready`; `parameter_proposal_candidate=false`, `parameter_change_allowed=false`, `learning_to_execution_ready=false` and `live_learning_allowed=false`. The optional BTC-USDC 24h monitor focused test now exists and uses local fixtures/mocks only; it does not start a service, call Coinbase, fetch market data or write trading state. The refreshed readiness decision map does not authorize live trading or parameter changes.

## Local Build Closure Note

`reports/d6/operator-24h-prerun-build-checklist-20260609.*` is the final local build checklist before an operator-started BTC-USDC 24h test. It may report `build_complete_for_operator_live_start_review=true`, but it also keeps `live_start_authorized=false` and `operator_manual_start_required=true`. `reports/d6/unresolved-blocker-ledger-20260609.*` separates locally complete work from ACK/live/external-code blockers and currently reports `remaining_locally_buildable_item_count=0`. Codex must not start the 24h test; live-start review, fresh Coinbase preflight and live action remain separate exact-ACK-gated operator steps.

## BTC-USDC Live-Start Decision Pack Note

`reports/d6/btc-usdc-24h-live-start-decision-pack-20260609.*` is report-only and decision-pack-only. It may report `ready_for_operator_fresh_preflight=true`, but `live_start_authorized=false`, `operator_manual_start_required=true` and `codex_must_not_start_live_test=true` remain hard boundaries. Codex did not run Coinbase product/balance preflight, did not start the loop and did not submit orders. The operator-only command templates in the pack are explicitly marked `OPERATOR ONLY - CODEX MUST NOT RUN`.

## All-Ticker 24h Workflow Readiness Note

`reports/d6/all-ticker-24h-workflow-readiness-pack-20260609.*` is the local all-ticker workflow readiness pack. It represents all 18 configured tickers and keeps `all_ticker_live_authorized=false` and `live_start_authorized=false`. BTC-USDC may be ready for operator fresh preflight; non-BTC tickers remain blocked by fresh live-readonly product-rule/balance/min-notional preflight and exact all-ticker ACK. Fixture evidence and paper replay are not Coinbase live proof.

`reports/d6/all-ticker-operator-preflight-command-pack-20260609.*` contains operator-only command templates. Every live/preflight/start/monitor/post-run command is marked `OPERATOR ONLY — CODEX MUST NOT RUN`. Codex must not run the all-ticker preflight, must not start an all-ticker run and must not enable all-ticker live.

`tools/show_all_ticker_24h_live_monitor.py` and `tools/build_all_ticker_24h_post_run_evidence_pack.py` are local scaffolds. They do not call Coinbase, fetch market data, start services, submit/cancel/replace/reprice, mutate state or authorize live trading. The post-run scaffold requires operator-supplied UTC start/stop windows for any future all-ticker evidence review.

`reports/d6/all-ticker-live-scope-guard-20260609.*` is the fail-closed live-scope guard. It must remain `OK` before any operator consideration of all-ticker preflight, and it fails closed if selected tests are not OK, open orders are nonzero, replication/follower/live learning/learning-to-execution/parameter mutation flags drift open, or all-ticker live is unexpectedly allowed.

## All-Ticker Live-Readonly Preflight And Shadow Parameters Note

`reports/d6/all-ticker-live-readonly-preflight-20260609.*` is the all-ticker live-readonly preflight pathway report. It is safe/local by default and does not call Coinbase. Current status is `not_run`: `all_ticker_live_readonly_preflight_attempted=false`, `all_ticker_live_readonly_preflight_passed=false`, `all_ticker_ready_for_operator_fresh_preflight=false` and `all_ticker_live_authorized=false`.

Update after real-readonly path build:
- `tools/show_all_ticker_live_readonly_preflight.py` now has explicit `--allow-coinbase-readonly`.
- Without that flag it still does not instantiate a Coinbase client or call Coinbase.
- With that flag it is bounded to product metadata and spot balance reads through a narrow adapter; no orders endpoint, submit, cancel, replace, reprice, lifecycle apply, state write, `.env` mutation, config mutation or parameter mutation is part of the path.
- The 2026-06-09 bounded readonly attempt was run and failed closed for all 18 tickers because Coinbase auth was unavailable: `coinbase_auth_missing_for_readonly_preflight`.
- `all_ticker_live_authorized=false` and `live_start_authorized=false` remain hard boundaries.
- The historical audit warning `filled_c43_without_position_created:phasec-BTCUSDC-smoke-20260524151451` is classified as `stale_historical_warning_known_safe` in the preflight report and remains visible; no state repair was performed.

Before an all-ticker manual run can be considered, the operator must separately authorize and run a fresh live-readonly product-rule/balance/min-notional preflight for every included ticker, review per-ticker blockers and provide an exact all-ticker ACK. Codex must not run that live-readonly preflight or any all-ticker live process unless a future prompt gives exact scoped ACK.

`reports/d6/shadow-parameter-approximation-pack-20260609.*` is review-only. It may identify categories that should be observed during/after a 24h test, but it does not approve values, does not optimize, does not rank for live use, does not mutate parameters and does not create a learning-to-execution bridge. Keep parameters unchanged for the 24h test unless a separate exact parameter-review/change ACK is provided.

Operator route guidance:
- BTC-USDC-only remains lower risk when BTC fresh preflight is green, selected harness is OK, open orders are zero, function audit is OK, live exits remain disabled, parameters remain unchanged and exact ACK exists.
- All-ticker is higher risk and remains blocked until every included ticker has a green live-readonly preflight, caps/max-new-order scope are reviewed, parameters remain unchanged and exact all-ticker ACK exists.

## All-Ticker Tiny Wrapper And Final Start Gate

Use `tools/operator_all_ticker_tiny_env.sh` only for an all-ticker operator review path. The wrapper is process-local, loads `.env` through Python/python-dotenv parsing, avoids shell-sourcing `.env`, and does not mutate `.env`, config or parameters.

Wrapper scope:
- `ALLOWED_TICKERS` and `PHASE_C_ALLOWED_TICKERS` are set to all 18 configured tickers.
- Tiny caps are conservative: `DEFAULT_QUOTE_SIZE_USDC=10`, `PHASE_C_MAX_ORDER_QUOTE=10`, `MAX_NOTIONAL_USD=10`, `AUTONOMOUS_MAX_ORDER_QUOTE=10`, `MAX_OPEN_POSITIONS=2`, max new orders per cycle `1`.
- Live exits, autonomous exits, D3 actual exit submit, replication, learning-to-execution, live learning and parameter changes are forced disabled.
- `ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=true` is set only when exact ACK `I_APPROVE_ALL_TICKER_TINY_24H_ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT_MAX_10_USDC` is present in `ALL_TICKER_TINY_ACTUAL_SUBMIT_ACK`.

Report-only gate without ACK:
```bash
tools/operator_all_ticker_tiny_env.sh .venv/bin/python tools/show_all_ticker_operator_live_start_gate.py \
  --json-out reports/d6/all-ticker-operator-live-start-gate-$(date -u +%Y%m%d).json \
  --markdown-out reports/d6/all-ticker-operator-live-start-gate-$(date -u +%Y%m%d).md
```

Operator-only ACKed gate check for later:
```bash
ALL_TICKER_TINY_ACTUAL_SUBMIT_ACK=I_APPROVE_ALL_TICKER_TINY_24H_ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT_MAX_10_USDC \
  tools/operator_all_ticker_tiny_env.sh .venv/bin/python tools/show_all_ticker_operator_live_start_gate.py \
  --json-out reports/d6/all-ticker-operator-live-start-gate-$(date -u +%Y%m%d).json \
  --markdown-out reports/d6/all-ticker-operator-live-start-gate-$(date -u +%Y%m%d).md
```

Operator-only live run command for later, DO NOT RUN YET:
```bash
ALL_TICKER_TINY_ACTUAL_SUBMIT_ACK=I_APPROVE_ALL_TICKER_TINY_24H_ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT_MAX_10_USDC \
  tools/operator_all_ticker_tiny_env.sh .venv/bin/python run_trader_loop.py
```

The final gate must always report `codex_must_not_start_live_test=true` and `operator_manual_start_required=true`. Codex must not run the ACKed gate or run command unless a future prompt explicitly authorizes the exact action; even then, Codex must not start `run_trader_loop.py` unless the prompt is specifically a live-start prompt.

## G. Troubleshooting Loop

Codex should patch only from local logs, reports and explicit operator evidence. Any repair/apply/cancel/submit/restart/config mutation still requires a separate exact ACK.

Stop condition for this runbook: wait for the operator to run preflight and, if desired, provide a separate exact live-start ACK. wachten tot trigger.
