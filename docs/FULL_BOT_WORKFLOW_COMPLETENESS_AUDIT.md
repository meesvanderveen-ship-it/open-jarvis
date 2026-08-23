# Full Bot Workflow Completeness Audit v1

This audit is report-only. It checks Full Bot workflow presence, report
connectivity, safety gates, current blockers and next actions without Coinbase
writes, live submit, cancel, replace, lifecycle apply, state writes, config
mutation or parameter mutation.

## Command

```bash
python3 tools/build_full_bot_workflow_completeness_audit.py \
  --json-out reports/d6/full-bot-workflow-completeness-audit-$(date -u +%Y%m%d).json \
  --markdown-out reports/d6/full-bot-workflow-completeness-audit-$(date -u +%Y%m%d).md
```

## Verdicts

- `ready_for_ack_gated_maker_buy_live_submit`: a Phase-C-ready candidate exists,
  no P0 safety blocker is present and actual submit still requires exact ACK.
- `blocked_by_missing_fresh_judge_and_risk`: selected candidates still need
  fresh BUY judge and deterministic live-risk evidence.
- `blocked_by_missing_fresh_candidate_refresh`: no Phase-C-ready candidate exists
  and candidate freshness/ranking must be refreshed.
- `blocked_by_missing_module_or_tool`: a required module, CLI or focused test is
  absent.
- `blocked_by_safety_gap`: a P0 safety condition blocks run readiness.

## Current Expected Use

Use the audit after refreshing the D.6/orchestrator/adapter/review/failure
matrix reports. The first real maker BUY submit is not allowed unless the audit
reports a Phase-C-ready ticker and the operator separately provides the exact
Full Bot maker BUY ACK. SELL, market orders, live exits, D3 actual exit submit,
replication, learning-to-execution and parameter mutation remain disabled.
