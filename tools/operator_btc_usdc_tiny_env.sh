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

export BOT_CONFIG_SKIP_DOTENV=true
export BTC_USDC_TINY_WRAPPER_MODE=true
export EXECUTION_MODE=live
export ALLOWED_TICKERS=BTC-USDC
export PHASE_C_ALLOWED_TICKERS=BTC-USDC
export DEFAULT_QUOTE_SIZE_USDC=10
export MAX_NOTIONAL_USD=10
export PHASE_C_MAX_ORDER_QUOTE=10
export AUTONOMOUS_MAX_ORDER_QUOTE=10
export MAX_OPEN_POSITIONS=1
export MAX_NEW_ORDERS_PER_CYCLE=1
export PHASE_C_MAX_OPEN_ENTRY_ORDERS=1
export PHASE_C_MAX_NEW_ORDERS_PER_CYCLE=1
export AUTONOMOUS_MAX_OPEN_ORDERS=1
export AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE=1
export ENABLE_LIMIT_ORDER_MANAGER=true
export ENABLE_LIVE_LIMIT_ORDERS=true
export ENABLE_LIVE_ENTRY_ORDERS=true
export ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS=true
export ENABLE_PHASE_C_LIVE_SUBMIT_INFRASTRUCTURE=true
export ENABLE_LIVE_EXIT_ORDERS=false
export ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT=false
export AUTONOMOUS_ALLOW_EXITS=false
export PHASE_C_DISABLE_EXIT_LIMIT_ORDERS=true
export AUTONOMOUS_ENTRY_ONLY_FIRST=true

if [[ "${BTC_USDC_TINY_ACTUAL_SUBMIT_ACK:-}" == "I_APPROVE_BTC_USDC_TINY_24H_ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT_MAX_10_USDC" ]]; then
  export ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=true
else
  export ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false
fi

if [[ "$#" -eq 0 ]]; then
  echo "usage: tools/operator_btc_usdc_tiny_env.sh <command> [args...]" >&2
  echo "example: tools/operator_btc_usdc_tiny_env.sh .venv/bin/python tools/show_btc_usdc_tiny_live_preflight.py" >&2
  exit 2
fi

exec "$@"
