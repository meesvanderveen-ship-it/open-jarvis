# Mode B Controlled Stop-Exit Activation Plan

Mode B is not active by default. It may only be prepared after a clean Mode A endurance run and may only be activated with an explicit operator ACK plus the required config flags.

Mode A remains valid without Mode B. In Mode A, controlled stop-exit is preview/reporting only: no cancel, no market/IOC sell submit and no local apply may run autonomously.

## When Mode B May Be Considered

- Mode A endurance run has clean runtime evidence.
- Single-process guard and cycle guard are clean.
- Atomic/state-write evidence is clean.
- D3 lifecycle is clean.
- No duplicate D3 exits or oversell signals occurred.
- Stop-exit previews are understandable and cancel-first sequencing is present.
- Open live orders have exchange order ids.

## Required Flags And ACK

- `ENABLE_CONTROLLED_STOP_MARKET_EXITS=true`
- `ENABLE_AUTONOMOUS_STOP_EXIT_APPLY=true`
- `MODE_B_CONTROLLED_STOP_EXIT_ACK=I_APPROVE_MODE_B_CONTROLLED_STOP_EXIT_APPLY`
- Exact operator ACK from the Mode B activation prompt. Without this exact value, config/readiness must fail closed.
- Approved parameter profile remains separate and hash-gated.

Readiness rules:

- Mode A readiness is false when autonomous stop-exit apply is active.
- Mode B readiness is separate from Mode A readiness.
- `ENABLE_AUTONOMOUS_STOP_EXIT_APPLY=true` without the exact ACK is a hard blocker.
- Market orders remain disabled. The controlled stop route uses only the governed `near_market_limit_ioc` plan, never a generic market-order route.
- Replication, neural execution, bounded exploration and automatic parameter mutation remain disabled unless separately approved by their own gates.

## Live Route

1. Detect stop breach or invalidation.
2. Detect any open TP/D3 SELL for the position.
3. If open TP exists, cancel existing TP first.
4. Verify Coinbase cancelled the TP.
5. Submit controlled near-market limit IOC SELL only after cancel evidence. Generic market orders remain disabled.
6. Verify terminal fill evidence from Coinbase.
7. Apply local lifecycle change only after fill evidence and the required ACK/config gates.

## Stop Conditions

- Duplicate SELL or oversell evidence.
- Missing exchange order id.
- Coinbase lookup/cancel/submit/fill verification failure.
- Lifecycle hook exception.
- Atomic/state-write errors.
- Process lock conflict.
- Any unexpected cancel/replace/apply outside the Mode B route.

## Rollback

- Set Mode B flags false.
- Leave Mode A stop-exit preview-only.
- Do not edit production state unless a separate state-repair ACK is issued.
- Rerun readiness and status tools before any new live decision.

> **STALE CURRENT-STATE WARNING — 2026-06-19**
>
> The 2026-06-14 claim that no local position exists is contradicted by the
> current read-only local state: `ADA-USDC` is recorded as `open`, with a
> linked filled C.4.3 BUY and D2/D3 still pending. This is not Coinbase-verified
> and is not authority for a repair, cancel, submit, or Mode-B action. Treat
> this document as a future activation plan only until operator-authorized
> read-only reconciliation has resolved the discrepancy.

## Monitoring

- `python3 tools/show_autonomous_live_run_status.py --json`
- `journalctl -u coinbase-bot -f --no-pager -l`
- `python3 tools/write_autonomous_live_run_report.py --since-hours 6 --json-out reports/live_runs/live-run-6h.json`

This document prepares Mode B only. It does not activate Mode B.
