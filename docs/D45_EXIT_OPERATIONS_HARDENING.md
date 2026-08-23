# D.45 Exit Operations Hardening v1

## Purpose

`bot/phase_d45_exit_operations_report.py` adds a report-only operator layer for the active D.4 replacement TP1 order while it waits at `76000.00`. It does not poll Coinbase by itself, does not submit, cancel, replace, reprice, apply lifecycle changes or write trading state.

The CLI wrapper is:

```bash
python3 tools/show_phase_d45_exit_operations_report.py --local-d45-fixture local.json --json
```

It accepts preloaded lifecycle poll evidence through `--lifecycle-poll-fixture` for fake tests or controlled operator workflows.

## Trigger Policy

The report classifies distance from the active limit:

| Band | Distance to `76000.00` | Poll rule |
| --- | ---: | --- |
| `near_target` | `<= 1.0%` | one read-only lifecycle poll is justified |
| `approaching_target` | `> 1.0%` and `<= 3.0%` | one read-only lifecycle poll is justified |
| `far_from_target` | `> 3.0%` | no poll unless operator, time, lifecycle or safety trigger exists |

Other valid triggers are an explicit operator request, fill/partial/terminal evidence hint, safety drift, or enough elapsed time when an updated lifecycle check is useful.

Safety drift blocks before polling.

## Branches

| Evidence | Branch | Next route |
| --- | --- | --- |
| No trigger | `open_keep_open` | `do_not_poll_wait_for_trigger` |
| `OPEN/open`, zero fills | `open_keep_open` | `keep_open` |
| `PARTIAL` or `FILLED` | `fill_evidence` | `Controlled D.3 Lifecycle Apply on Fill Evidence v1` |
| `CANCELLED`, `EXPIRED` or `REJECTED` | `terminal_evidence` | `Controlled D.3 Terminal Closeout Reconcile v1` |
| local safety drift or poll uncertainty | fail closed | P0/diagnostic review |

Required future ACK for the D.3 lifecycle manager route:

```text
I_UNDERSTAND_AND_APPROVE_D3_OPEN_EXIT_LIFECYCLE_APPLY
```

The inner D.3 live-exit reconcile ACK remains:

```text
I_UNDERSTAND_AND_APPROVE_D3_LIVE_EXIT_RECONCILIATION_APPLY
```

## D.5 No-Fill/Stale Metrics

D.5 remains report-only and now includes:

- `target_distance_abs`
- `target_distance_pct`
- `target_distance_band`
- `stale_order_age_seconds`
- `no_fill_duration_seconds`
- `no_fill_recommendation_label`

`learning_to_execution_allowed` remains `false`.

## Safety

This layer is offline/report-only. It confirms:

- no Coinbase submit
- no Coinbase cancel
- no Coinbase replace
- no Coinbase write
- no live action
- no trading-state write
- no learning-to-execution
