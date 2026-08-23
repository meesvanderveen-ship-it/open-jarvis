# Full Bot Orchestrator v1

Full Bot Orchestrator v1 is a dry-run/report layer that combines entry, exit,
market-order, order-management, lifecycle and learning candidates into one
operator review artifact.

This sprint does not enable live trading. It does not submit, cancel, replace,
place market orders, execute SELL orders, apply lifecycle fills, mutate `.env`,
mutate config, mutate parameters, enable replication or write trading state.

## Policy

- `max_open_orders_total = 5`
- `max_quote_per_order = 20 USDC`
- `max_total_reserved_buy_quote = 100 USDC`
- `max_open_orders_per_ticker = 1`
- `max_new_orders_per_cycle = 2`
- `max_open_positions = 5`

## Authorization Matrix

- BUY maker entry: ACK-gated through the existing Phase-C strict approve route.
- Pattern/near-miss BUY: preview only in v1.
- SELL maker exit: preview only in v1; future D.3/D.4 ACK required.
- Market BUY: preview only; future explicit market ACK required.
- Market SELL: preview only; future emergency/edge ACK required.
- Cancel/replace/reprice: preview only; future D.4 ACK required.
- Learning: observe/report only.
- Replication: disabled.
- Parameter mutation: disabled.

## Operator Command

```bash
python3 tools/build_full_bot_orchestrator_report.py \
  --json-out reports/d6/full-bot-orchestrator-YYYYMMDD.json \
  --markdown-out reports/d6/full-bot-orchestrator-YYYYMMDD.md
```

The recommended next live sprint is an ACK-gated tiny run that enables only
maker BUY entries through the existing Phase-C path first. Controlled SELL exits
and market orders should be separate later gates.

## Maker BUY Live Adapter v1

`bot/full_bot_maker_buy_live_adapter.py` connects Full Bot Orchestrator entry
candidates to the existing Phase-C maker BUY guard/submit preparation route.
The normal command is preview-only: it selects at most two eligible maker BUY
candidates, rejects SELL/market/blocked candidates, enforces max 20 USDC per
order, max five open orders, max one open order per ticker and max 100 USDC
reserved BUY quote, then runs Phase-C guard and payload preparation with
`submit_live=False`.

Preview command:

```bash
python3 tools/build_full_bot_maker_buy_live_adapter_report.py \
  --orchestrator-report reports/d6/full-bot-orchestrator-$(date -u +%Y%m%d).json \
  --json-out reports/d6/full-bot-maker-buy-live-adapter-$(date -u +%Y%m%d).json \
  --markdown-out reports/d6/full-bot-maker-buy-live-adapter-$(date -u +%Y%m%d).md
```

Future actual submit remains default-off and requires this exact ACK plus
`--actual-submit`, all adapter caps and all Phase-C guards:

```text
I_APPROVE_FULL_BOT_MAKER_BUY_LIVE_MAX_5_ORDERS_MAX_20_USDC_NO_SELL_NO_MARKET
```

Do not run the actual-submit command until a separate operator prompt gives that
exact ACK. SELL, market orders, live exits, D3 actual exit submit, replication,
learning-to-execution and parameter mutation remain disabled.
