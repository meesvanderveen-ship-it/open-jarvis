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
ALL_TICKER_ACK="I_APPROVE_ALL_TICKER_TINY_24H_ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT_MAX_10_USDC"

export BOT_CONFIG_SKIP_DOTENV=true
export ALL_TICKER_TINY_WRAPPER_MODE=true
export OPERATOR_ALL_TICKER_TINY_ENV_READY=true
export EXECUTION_MODE=live
export ALLOWED_TICKERS="${ALL_TICKERS}"
export PHASE_C_ALLOWED_TICKERS="${ALL_TICKERS}"
export DEFAULT_QUOTE_SIZE_USDC=10
export PHASE_C_MAX_ORDER_QUOTE=10
export MAX_NOTIONAL_USD=10
export AUTONOMOUS_MAX_ORDER_QUOTE=10
export MAX_OPEN_POSITIONS=2
export MAX_NEW_ORDERS_PER_CYCLE=1
export PHASE_C_MAX_OPEN_ENTRY_ORDERS=1
export PHASE_C_MAX_NEW_ORDERS_PER_CYCLE=1
export AUTONOMOUS_MAX_OPEN_ORDERS=2
export AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE=1
export ENABLE_LIMIT_ORDER_MANAGER=true
export ENABLE_LIVE_LIMIT_ORDERS=true
export ENABLE_LIVE_ENTRY_ORDERS=true
export ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS=true
export ENABLE_PHASE_C_LIVE_SUBMIT_INFRASTRUCTURE=true
export ENABLE_LIVE_EXIT_ORDERS=false
export AUTONOMOUS_ALLOW_EXITS=false
export ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT=false
export PHASE_C_DISABLE_EXIT_LIMIT_ORDERS=true
export AUTONOMOUS_ENTRY_ONLY_FIRST=true
export REPLICATION_ENABLED=false
export LEARNING_TO_EXECUTION_READY=false
export LEARNING_TO_EXECUTION_ALLOWED=false
export LIVE_LEARNING_ALLOWED=false
export PARAMETER_CHANGE_ALLOWED=false

if [[ "${ALL_TICKER_TINY_ACTUAL_SUBMIT_ACK:-}" == "${ALL_TICKER_ACK}" ]]; then
  export ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=true
else
  export ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false
fi

if [[ "$#" -eq 0 ]]; then
  echo "usage: tools/operator_all_ticker_tiny_env.sh <command> [args...]" >&2
  echo "scope: ${ALL_TICKERS}" >&2
  echo "caps: DEFAULT_QUOTE_SIZE_USDC=${DEFAULT_QUOTE_SIZE_USDC} PHASE_C_MAX_ORDER_QUOTE=${PHASE_C_MAX_ORDER_QUOTE} MAX_NOTIONAL_USD=${MAX_NOTIONAL_USD} MAX_OPEN_POSITIONS=${MAX_OPEN_POSITIONS}" >&2
  echo "submit: ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=${ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT} requires ${ALL_TICKER_ACK}" >&2
  echo "exits/replication/learning/parameters disabled: ENABLE_LIVE_EXIT_ORDERS=${ENABLE_LIVE_EXIT_ORDERS} AUTONOMOUS_ALLOW_EXITS=${AUTONOMOUS_ALLOW_EXITS} ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT=${ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT} REPLICATION_ENABLED=${REPLICATION_ENABLED} LEARNING_TO_EXECUTION_READY=${LEARNING_TO_EXECUTION_READY} LIVE_LEARNING_ALLOWED=${LIVE_LEARNING_ALLOWED} PARAMETER_CHANGE_ALLOWED=${PARAMETER_CHANGE_ALLOWED}" >&2
  exit 2
fi

exec "$@"
