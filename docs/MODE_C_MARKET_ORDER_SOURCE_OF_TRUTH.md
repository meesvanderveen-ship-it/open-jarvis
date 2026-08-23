# Mode C Market Order Source Of Truth

Full workflow baseline keeps market order flags disabled:

- `MARKET_ORDER_ENABLED=false`
- `ENABLE_MARKET_ORDERS=false`
- `ALLOW_MARKET_ORDERS=false`

Full POC Mode C may enable market or near-market close capability only when all three market flags are true, exact `MODE_C_MARKET_ORDER_ACK=I_APPROVE_MARKET_ORDERS_FOR_POC_20_100_NO_REPLICATION` is present, and replication is fully disabled.

Mode C is restricted to controlled close/stop routing. It does not authorize arbitrary speculative market entries. D2, D3, no-naked-sell, no-oversell, cancel-first, Coinbase verification, and terminal fill evidence rules remain mandatory.

