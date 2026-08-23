# Market Intelligence Context

`bot/market_intelligence_context.py` builds a read-only external context layer for the trading bot. It is context only:

- `can_authorize_execution=false`
- `can_block_execution=false`
- `can_mutate_parameters=false`

It must never approve trades, bypass deterministic risk, force market orders, skip D2/D3, activate stop exits, or mutate parameters.

## Sources

- DefiLlama free API: `https://api.llama.fi`
- DefiLlama stablecoins compatibility API: `https://stablecoins.llama.fi`
- Coin Metrics Community API: `https://community-api.coinmetrics.io/v4`
- Santiment GraphQL: `https://api.santiment.net/graphql`, optional and disabled by default unless enabled with an API key

Coinbase remains the source for execution, raw market data, orderbook, fills, fees, orders, positions, and exchange status.

## Commands

```bash
python3 tools/build_market_intelligence_context.py --json
python3 tools/show_market_intelligence_context.py --json
```

Fixture/no-network mode:

```bash
python3 tools/build_market_intelligence_context.py --no-network --json
```

Options:

- `--ttl-minutes 60`
- `--sources defillama,coinmetrics,santiment`
- `--json-out path/to/report.json`
- `--no-network`

## State And Logs

- Current state: `state/market_intelligence_context.json`
- Raw fetch snapshots: `logs/market_intelligence_fetches.jsonl`

State writes use the existing atomic JSON helper. Fetch logs are append-only JSONL snapshots for observability.

## Environment

Do not mutate `.env` automatically. Suggested operator-controlled settings:

```env
ENABLE_MARKET_INTELLIGENCE_CONTEXT=true
MARKET_INTELLIGENCE_CONTEXT_TTL_MINUTES=60
ENABLE_DEFILLAMA_CONTEXT=true
ENABLE_COINMETRICS_CONTEXT=true
ENABLE_SANTIMENT_CONTEXT=false
SANTIMENT_API_KEY=
MARKET_INTELLIGENCE_CONTEXT_STRICT_NETWORK=false
```

Defaults:

- DefiLlama enabled
- Coin Metrics enabled
- Santiment disabled without key
- context-only
- no execution authority

## Failure Behavior

Network/API failures produce warnings and unavailable/null fields. They do not crash the workflow and do not block execution because this layer has no execution authority.

DefiLlama stablecoin fallback order:

1. `https://api.llama.fi/stablecoins`
2. `https://stablecoins.llama.fi/stablecoins`
3. `stablecoincharts/all` historical fallback, first on `api.llama.fi` then on the stablecoins host
4. `stablecoinchains` fallback, first on `api.llama.fi` then on the stablecoins host

404s on optional stablecoin endpoints are warnings only. DefiLlama can remain available when TVL, DEX volume, or perps/open-interest context is present.

Coin Metrics uses the community API and performs catalog discovery before fetching timeseries. Only discovered BTC/ETH community-accessible metrics are requested. If catalog or metrics access returns 403, Coin Metrics degrades to unavailable/unknown with warnings.

Santiment is optional. If disabled, missing a key, rate-limited, or unavailable, it degrades to:

```json
{"available": false, "reason": "disabled_or_missing_api_key"}
```

`tools/show_market_intelligence_context.py --json` includes source status and collected warnings:

```json
{
  "available": true,
  "stale": false,
  "sources": {
    "defillama": "available",
    "coinmetrics": "partial",
    "santiment": "disabled"
  },
  "warnings": [
    "santiment:disabled_or_missing_api_key"
  ]
}
```

## Feature Pack

The strategy feature pack receives:

```json
{
  "decision_context": {
    "external_context": {
      "market_intelligence": {
        "available": true,
        "stale": false,
        "summary": {
          "liquidity_regime": "neutral",
          "network_regime": "unknown",
          "crowd_regime": "unknown",
          "risk_warnings": [],
          "positive_context": []
        },
        "can_authorize_execution": false,
        "can_block_execution": false,
        "can_mutate_parameters": false
      }
    }
  }
}
```

This can inform prompts, audits, and risk warnings. It cannot authorize or block execution.
