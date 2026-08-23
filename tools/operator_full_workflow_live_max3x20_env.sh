#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo ".env not found; refusing to build operator override environment" >&2
  exit 2
fi

eval "$(
  .venv/bin/python - <<'PY'
from pathlib import Path
import shlex

try:
    from dotenv import dotenv_values
except ImportError:
    dotenv_values = None

values = {}
if dotenv_values is not None:
    values = {k: v for k, v in dotenv_values(".env").items() if k and v is not None}
else:
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()

for key, value in values.items():
    print(f"export {key}={shlex.quote(str(value))}")
PY
)"

ALL_TICKERS="BTC-USDC,ETH-USDC,SOL-USDC,XRP-USDC,ADA-USDC,LINK-USDC,AVAX-USDC,DOGE-USDC,SUI-USDC,LTC-USDC,HBAR-USDC,ATOM-USDC,NEAR-USDC,APT-USDC,INJ-USDC,ARB-USDC,OP-USDC,UNI-USDC"
FULL_WORKFLOW_ACK="I_APPROVE_FULL_WORKFLOW_LIVE_MAX_3_ORDERS_MAX_20_USDC_BUY_AND_SELL_NO_MARKET_NO_REPLICATION"
ACK_EXACT=false
if [[ "${FULL_WORKFLOW_LIVE_ACK:-}" == "${FULL_WORKFLOW_ACK}" ]]; then
  ACK_EXACT=true
fi

export BOT_CONFIG_SKIP_DOTENV=true
export OPERATOR_FULL_WORKFLOW_LIVE_MAX3X20_ENV_READY=true
export FULL_WORKFLOW_LIVE_REQUIRED_ACK="${FULL_WORKFLOW_ACK}"

export EXECUTION_MODE=live
export ALLOWED_TICKERS="${ALL_TICKERS}"
export PHASE_C_ALLOWED_TICKERS="${ALL_TICKERS}"

export MAX_OPEN_POSITIONS=3
export AUTONOMOUS_MAX_OPEN_ORDERS=3
export PHASE_C_MAX_OPEN_ENTRY_ORDERS=3
export MAX_NEW_ORDERS_PER_CYCLE=1
export AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE=1
export PHASE_C_MAX_NEW_ORDERS_PER_CYCLE=1

export DEFAULT_QUOTE_SIZE_USDC=20.00
export MAX_NOTIONAL_USD=20.00
export PHASE_C_MAX_ORDER_QUOTE=20.00
export AUTONOMOUS_MAX_ORDER_QUOTE=20.00
export PHASE_D3_MAX_EXIT_ORDER_QUOTE=20.00
export PHASE_D3_MAX_OPEN_EXIT_ORDERS=3
export PHASE_D3_MAX_NEW_EXIT_ORDERS_PER_CYCLE=1

export ENABLE_LIVE_ENTRY_ORDERS=true
export ENABLE_LIVE_LIMIT_ORDERS=true
export ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS=true
export ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE=true
export ENABLE_LIMIT_ORDER_MANAGER=true
export ENABLE_PHASE_C_LIVE_SUBMIT_INFRASTRUCTURE=true
export ENABLE_FULL_WORKFLOW_LIVE_MODE="${ACK_EXACT}"

export ENABLE_PHASE_C43_LIFECYCLE_ORCHESTRATOR=true
export PHASE_C43_LIFECYCLE_ALLOW_COINBASE_POLL="${ACK_EXACT}"
export PHASE_C43_LIFECYCLE_APPLY_LOCAL="${ACK_EXACT}"
export PHASE_C43_LIFECYCLE_BUILD_D2_PLAN="${ACK_EXACT}"
export PHASE_C43_LIFECYCLE_PERSIST_D2_PLAN="${ACK_EXACT}"
export PHASE_C43_LIFECYCLE_BUILD_D3_PREVIEW="${ACK_EXACT}"
export PHASE_C43_LIFECYCLE_MAX_POLL_ORDERS_PER_CYCLE=3
export PHASE_C43_LIFECYCLE_MAX_APPLY_ACTIONS_PER_CYCLE=3

if [[ "${ACK_EXACT}" == "true" ]]; then
  export ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=true
  export ENABLE_LIVE_EXIT_ORDERS=true
  export AUTONOMOUS_ALLOW_EXITS=true
  export ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT=true
  export PHASE_C_DISABLE_EXIT_LIMIT_ORDERS=false
  export AUTONOMOUS_ENTRY_ONLY_FIRST=false
  export PHASE_D3_RUNTIME_SUBMIT_ACK="I_UNDERSTAND_AND_APPROVE_D3_CONTROLLED_REDUCE_ONLY_LIVE_EXITS"
else
  export ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false
  export ENABLE_LIVE_EXIT_ORDERS=false
  export AUTONOMOUS_ALLOW_EXITS=false
  export ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT=false
  export PHASE_C_DISABLE_EXIT_LIMIT_ORDERS=true
  export AUTONOMOUS_ENTRY_ONLY_FIRST=true
  export PHASE_D3_RUNTIME_SUBMIT_ACK=""
fi

export REPLICATION_ENABLED=false
export MARKET_ORDER_ENABLED=false
export ENABLE_MARKET_ORDERS=false
export ALLOW_MARKET_ORDERS=false
export LEARNING_TO_EXECUTION_READY=false
export LEARNING_TO_EXECUTION_ALLOWED=false
export LIVE_LEARNING_ALLOWED=false
export PARAMETER_CHANGE_ALLOWED=false

if [[ "$#" -eq 0 ]]; then
  echo "usage: tools/operator_full_workflow_live_max3x20_env.sh <command> [args...]" >&2
  echo "ack_exact=${ACK_EXACT}; required=${FULL_WORKFLOW_ACK}" >&2
  echo "mode=${EXECUTION_MODE} full_workflow=${ENABLE_FULL_WORKFLOW_LIVE_MODE}" >&2
  echo "caps: max_open_orders=${AUTONOMOUS_MAX_OPEN_ORDERS} max_positions=${MAX_OPEN_POSITIONS} max_new_per_cycle=${MAX_NEW_ORDERS_PER_CYCLE} quote=${DEFAULT_QUOTE_SIZE_USDC} max_notional=${MAX_NOTIONAL_USD}" >&2
  echo "entry: live=${ENABLE_LIVE_ENTRY_ORDERS}/${ENABLE_LIVE_LIMIT_ORDERS} phase_c_actual_submit=${ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT}" >&2
  echo "lifecycle: poll=${PHASE_C43_LIFECYCLE_ALLOW_COINBASE_POLL} apply=${PHASE_C43_LIFECYCLE_APPLY_LOCAL} d2=${PHASE_C43_LIFECYCLE_BUILD_D2_PLAN} d3_preview=${PHASE_C43_LIFECYCLE_BUILD_D3_PREVIEW}" >&2
  echo "exits: live=${ENABLE_LIVE_EXIT_ORDERS} autonomous=${AUTONOMOUS_ALLOW_EXITS} d3_actual=${ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT} phase_c_exit_disabled=${PHASE_C_DISABLE_EXIT_LIMIT_ORDERS} entry_only_first=${AUTONOMOUS_ENTRY_ONLY_FIRST}" >&2
  echo "disabled: market=${MARKET_ORDER_ENABLED}/${ENABLE_MARKET_ORDERS}/${ALLOW_MARKET_ORDERS} replication=${REPLICATION_ENABLED} learning=${LEARNING_TO_EXECUTION_ALLOWED}/${LIVE_LEARNING_ALLOWED} parameters=${PARAMETER_CHANGE_ALLOWED}" >&2
  exit 2
fi

exec "$@"
