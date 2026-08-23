# Full Bot Real Fresh Review Runner

`tools/run_full_bot_real_fresh_review_runner.py` produces no-submit fresh judge and deterministic live-risk evidence for current Full Bot maker BUY candidates.

Safety boundaries:

- no live submit
- no Coinbase write/cancel/replace calls
- no trading-state writes
- no `.env` mutation
- no bot start
- BUY limit-maker review only

The runner consumes the existing D.6/orchestrator/adapter/near-miss/failure reports, builds structured per-ticker review requests, optionally calls the configured OpenAI judge, then runs the existing deterministic C4.3 risk snapshot and Phase-C guard in report-only mode.

Output files:

- `reports/d6/real-fresh-judge-risk-evidence-YYYYMMDD.json`
- `reports/d6/real-fresh-judge-risk-evidence-YYYYMMDD.md`

If the judge is unavailable or returns `wait`/`reject`, the evidence remains honest and no approval is fabricated. Actual submit stays a future exact-ACK-gated command.

