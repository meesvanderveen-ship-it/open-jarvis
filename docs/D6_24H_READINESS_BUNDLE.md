# D.6 24h Readiness Bundle

This bundle prepares the non-live workflow components needed before a future 24h controlled live-test prompt.

## Scope

- Report-only and local-file-only.
- No Coinbase calls.
- No OpenAI API calls.
- No data fetch.
- No live order action.
- No lifecycle apply.
- No local repair apply.
- No config, prompt, strategy, risk or parameter mutation.
- No parameter search.
- No learning-to-execution.

## What It Adds

- Multi-ticker coverage and cached-data gap map for the configured universe.
- Bounded future data-ingest command plan, left behind an explicit data-fetch ACK.
- Cached-only baseline feasibility check where local candle data exists.
- 24h live-run evidence capture schema.
- Future preflight v2 structure for a BTC-USDC-only controlled live-test prompt.

## Current Expected Result

BTC-USDC can be prepared for future ACK review after a final safety refresh. The all-ticker 24h live test remains blocked because the other configured tickers do not have local cached coverage, dataset-quality artifacts, cached baseline inputs or live lifecycle evidence.

The bundle does not authorize a live test.
