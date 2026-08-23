# D.3 / D.4 test coverage mapping

## 1. Purpose

Dit document koppelt de bestaande testset systematisch aan de D.3/D.4 test- en safety-matrix.

Doelen:

- zichtbaar maken welke D.3 reconcile branches al testdekking hebben
- zichtbaar maken welke safety-invarianten al testdekking hebben
- expliciet maken waar coverage nog partial of missing is
- een concrete test-backlog maken vóór verdere D.3 reconcile/apply, cancel-only en D.4 design/pilot werk

Dit document is planning-only en geeft geen toestemming voor live acties.

## 2. Existing test inventory

| test file | relevant area | likely coverage | notes |
| --- | --- | --- | --- |
| `tests/test_phase_d3_live_exit_reconciliation.py` | D.3 reconcile branches | OPEN, PARTIAL, FILLED, CANCELLED, EXPIRED, REJECTED, unknown/fail-closed, duplicate blockers, reservation deltas | kernbestand voor D.3 reconcile dekking |
| `tests/test_phase_d3_controlled_live_exits.py` | D.3 exit intent / readiness | duplicate exit guard, no oversell, reservation governance presence, product-rule rounding, report semantics | belangrijk voor preview-side invarianten |
| `tests/test_phase_d3_reservation_governance.py` | reservation governance | available/reserved/managed base semantics, read-only behavior, fail-closed coherence | dekt read-only reservation snapshot, niet volledige state-machine |
| `tests/test_phase_d3_controlled_exit_pilot.py` | D.3 pilot gating | plan fingerprint, replication block, live-context preview, product rules, reject semantics, reservation coherence gate | belangrijk voor pre-submit safety en latere D.4 pilot criteria |
| `tests/test_phase_d3_open_exit_order_governance.py` | stale-open governance | keep-open vs stale/open governance review, product rules presence, reservation fields | relevant voor D.4 stale-threshold voorbereiding |
| `tests/test_phase_d3_cancel_replace_governance.py` | cancel/replace governance | keep-open, reconcile-first, pending-cancel, candidate/governance branching | belangrijkste huidige D.4-governance voorwerk |
| `tests/test_phase_d3_base_balance_preflight.py` | base-balance preflight | read-only safety, no submit/cancel/replace, live/local coherence guards | ondersteunt no-oversell/pre-submit readiness |
| `tests/test_phase_d3_rejected_submit_cleanup.py` | reject cleanup | rejected local record cleanup logic, exact-record targeting | relevant voor REJECTED branch, niet voor main reconcile apply |
| `tests/test_live_exit_gate.py` | central live-exit gate | global SELL gate behavior | kern safety-gate test |
| `tests/test_coinbase_executor_live_exit_gate.py` | executor SELL blocking | executor route geblokkeerd zonder live-exit toestemming | dekt legacy executor path |
| `tests/test_strategy_engine_live_exit_gate.py` | StrategyEngine legacy SELL blocking | blocked legacy close/reduce path, blocked logging | dekt legacy StrategyEngine SELL-route |
| `tests/test_function_preservation_audit.py` | audit / preservation | read-only audit, gate coverage presence, safety preservation | ondersteunt coverage/audit inventaris, geen branchlogica |
| `tests/test_phase_d2_position_executor.py` | D.2 plan / fingerprint | plan fingerprint stability, min-order-quote fallback, TP sizing behavior | belangrijk voor post-reconcile D.2 revalidation |
| `tests/test_phase_d23_hardening_v1.py` | D.2/D.3 hardening | filled_quote normalization, C.4.5 to D.2 bridge assumptions | indirect relevant voor fill evidence normalization |
| `tests/test_coinbase_order_snapshot.py` | snapshot normalization | cancelled/filled/partial status normalization, filled quote/base derivation | belangrijk voor reconcile input correctness |
| `tests/test_phase_c44_poll_to_apply_closeout.py` | C.4.4 governance | preview-before-apply, state mutation blocked in preview, final/filled branch wrappers | indirect relevant voor OPEN/no-apply discipline |
| `tests/test_phase_c43_lifecycle_orchestrator.py` | lifecycle orchestration | cancelled/fill apply patterns, preview vs apply semantics | indirect relevant als governance precedent |
| `tests/test_phase_c43_one_entry_smoke_test.py` | replication / follower isolation | replication disabled requirement, master-only rules | indirect relevant voor D.3 isolation invariant |
| `tests/test_phase_c43_tiny_residual_recovery.py` | recovery / dust semantics | tiny residual recovery, dust close reasons, guarded apply | relevant voor dust edgecases, maar niet D.3 reconcile itself |
| `tests/test_strategy_engine_tiny_residual_phasec_pilot.py` | runtime keep-open behavior | keep-open policy around tiny residual governance | relevant voor state coherence around open exit holds |

## 3. Coverage by D.3 reconcile branch

| branch | existing tests | coverage status: covered / partial / missing | missing assertions | priority |
| --- | --- | --- | --- | --- |
| `OPEN/open keep_open` | `tests/test_phase_d3_live_exit_reconciliation.py`, `tests/test_phase_c44_poll_to_apply_closeout.py` | covered | extra end-to-end assertion dat order counts + positions + reservation exact ongewijzigd blijven zou nuttig zijn | P0 |
| `PARTIAL` | `tests/test_phase_d3_live_exit_reconciliation.py` | partial | meerdere partial fills, fee deltas, dust-restant, min-size after partial, post-apply D.2/D.3 preview-only assertions | P0 |
| `FILLED` | `tests/test_phase_d3_live_exit_reconciliation.py` | partial | full-fill met available-vs-reserved semantics, post-apply fingerprint revalidation, open order counts sanity, D.2 follow-up assertions | P0 |
| `CANCELLED` | `tests/test_phase_d3_live_exit_reconciliation.py` | partial | post-cancel closeout coherence, reservation release + new preview readiness, explicit no-new-SELL-before-closeout assertion | P0 |
| `EXPIRED` | `tests/test_phase_d3_live_exit_reconciliation.py` | partial | same as CANCELLED plus stale-open governance handoff expectations | P0 |
| `REJECTED` | `tests/test_phase_d3_live_exit_reconciliation.py`, `tests/test_phase_d3_rejected_submit_cleanup.py` | partial | reconcile-path reject in existing open lifecycle context, no false fill evidence, post-reject preview/fingerprint expectations | P0 |
| `UNKNOWN/network failure` | `tests/test_phase_d3_live_exit_reconciliation.py`, `tests/test_coinbase_order_snapshot.py` | partial | explicit network-failure-is-not-trading-signal assertions across snapshot + reconcile + governance layers | P0 |

## 4. Coverage by safety invariant

| invariant | existing tests | coverage status | missing assertions | priority |
| --- | --- | --- | --- | --- |
| no duplicate exit | `tests/test_phase_d3_controlled_live_exits.py`, `tests/test_phase_d3_live_exit_reconciliation.py` | covered | extra post-closeout duplicate reset assertion | P0 |
| no oversell | `tests/test_phase_d3_controlled_live_exits.py`, `tests/test_phase_d3_base_balance_preflight.py` | partial | oversell after partial reconcile and open-hold semantics | P0 |
| no negative base | `tests/test_phase_d3_live_exit_reconciliation.py` | partial | explicit assertions for every final branch and dust/min-size edgecases | P0 |
| reservation release | `tests/test_phase_d3_live_exit_reconciliation.py`, `tests/test_phase_d3_reservation_governance.py` | partial | open order counts + reservation + position coherence in one assertion set | P0 |
| partial reservation handling | `tests/test_phase_d3_live_exit_reconciliation.py` | partial | multiple partial cycles, fees, remaining reservation under minimum | P0 |
| dust/min-size | `tests/test_phase_d2_position_executor.py`, `tests/test_phase_c43_tiny_residual_recovery.py` | partial | explicit D.3 reconcile dust/min-size behavior after PARTIAL/FILLED/CANCELLED | P0 |
| product-rules increments/min quote | `tests/test_phase_d3_controlled_live_exits.py`, `tests/test_phase_d3_controlled_exit_pilot.py`, `tests/test_phase_d3_open_exit_order_governance.py` | partial | reconcile-path remaining-size/increment interactions, replacement rounding cases | P1 |
| linked position consistency | `tests/test_phase_d3_live_exit_reconciliation.py` | partial | mismatch matrix for ticker, position id, client order id, exchange order id in cancel-first flow | P0 |
| D.2 fingerprint revalidation | `tests/test_phase_d2_position_executor.py`, `tests/test_phase_d3_controlled_exit_pilot.py` | partial | explicit post-reconcile lifecycle-change -> new preview/fingerprint assertions | P1 |
| central live-exit gate | `tests/test_live_exit_gate.py`, `tests/test_coinbase_executor_live_exit_gate.py`, `tests/test_strategy_engine_live_exit_gate.py` | covered | mapping to future D.4 replace/cancel-first orchestration | P1 |
| legacy SELL-route blocked | `tests/test_strategy_engine_live_exit_gate.py`, `tests/test_coinbase_executor_live_exit_gate.py`, `tests/test_function_preservation_audit.py` | covered | audit artifact listing all guarded SELL entrypoints | P1 |
| replication/follower isolation | `tests/test_phase_c43_one_entry_smoke_test.py`, `tests/test_phase_d3_controlled_exit_pilot.py` | partial | explicit D.3 reconcile/governance blocker tests when replication enabled | P1 |
| no state mutation at `OPEN/open` | `tests/test_phase_d3_live_exit_reconciliation.py`, `tests/test_phase_c44_poll_to_apply_closeout.py` | covered | extra explicit assertion for open order counts and position snapshot equality | P0 |

## 5. D.4 readiness coverage

| feature | existing tests / assets | coverage status | missing assertions | priority |
| --- | --- | --- | --- | --- |
| stale thresholds | `tests/test_phase_d3_open_exit_order_governance.py` | partial | exact threshold boundaries and escalation rules | P2 |
| cancel-candidate criteria | `tests/test_phase_d3_cancel_replace_governance.py` | partial | concrete candidate threshold matrix and evidence requirements | P1 |
| replace-candidate criteria | `tests/test_phase_d3_cancel_replace_governance.py` | partial | explicit replace-candidate transitions and blockers | P1 |
| cancel-first sequence | `tests/test_phase_d3_cancel_replace_governance.py`, `docs/D3_OPEN_EXIT_OPERATOR_RUNBOOK.md` | partial | full modeled sequence: cancel -> poll -> closeout -> preview -> fingerprint | P1 |
| no atomic cancel+replace | `tests/test_phase_d3_cancel_replace_governance.py` | partial | explicit assertion that replace cannot proceed in same step/session | P1 |
| reservation-aware replacement | `tests/test_phase_d3_reservation_governance.py`, `tests/test_phase_d3_cancel_replace_governance.py` | partial | replacement after partial release and after full closeout | P2 |
| trailing activation/distance | indirect via `tests/test_phase_d2_position_executor.py` | missing | D.4-specific trailing governance, activation thresholds, no-live-submit behavior | P2 |
| product-rules gating | `tests/test_phase_d3_controlled_exit_pilot.py`, `tests/test_phase_d3_open_exit_order_governance.py`, `tools/show_coinbase_product_rules.py` | partial | cancel/replace replacement rounding and min-quote after repricing | P2 |
| logging/observability | `tests/test_function_preservation_audit.py`, governance/report tests | partial | explicit log/event expectations for cancel-first and replacement decisions | P2 |
| controlled pilot criteria | `tests/test_phase_d3_controlled_exit_pilot.py` | partial | D.4 pilot criteria after current lifecycle, including cancel-first preconditions | P2 |

## 6. Concrete test backlog

P0:

- voorgestelde testnaam: `test_d3_partial_fill_multiple_deltas_preserve_remaining_reservation`
  - doel: bewijzen dat meerdere partial fills alleen nieuwe delta verwerken
  - scenario: zelfde open D.3 order krijgt twee oplopende partial snapshots
  - expected result: idempotent delta processing, resterende reservation coherent, geen negatieve base
  - files likely to touch later: `tests/test_phase_d3_live_exit_reconciliation.py`, `bot/phase_d3_live_exit_reconciliation.py`
  - live safety note: puur local reconcile, geen Coinbase call

- voorgestelde testnaam: `test_d3_filled_apply_revalidates_available_reserved_managed_base_semantics`
  - doel: valideren dat full fill correct werkt met available-vs-reserved semantics
  - scenario: open hold semantics met `position_size_base < bot_managed_base`, full fill snapshot
  - expected result: reservation release correct, resulting available and managed base coherent, geen negatieve base
  - files likely to touch later: `tests/test_phase_d3_live_exit_reconciliation.py`, `bot/phase_d3_live_exit_reconciliation.py`
  - live safety note: no submit/apply outside local test fixtures

- voorgestelde testnaam: `test_d3_cancelled_closeout_requires_coherent_post_closeout_preview_state`
  - doel: voorkomen dat cancel-closeout branch als klaar wordt gezien zonder preview readiness
  - scenario: cancelled snapshot, coherent release, daarna preview prerequisites controleren
  - expected result: closeout coherent, maar geen nieuwe SELL; preview/fingerprint alleen read-only vervolg
  - files likely to touch later: `tests/test_phase_d3_live_exit_reconciliation.py`, eventueel `tests/test_phase_d3_controlled_live_exits.py`
  - live safety note: geen cancel uitvoeren, alleen gesimuleerde snapshots

- voorgestelde testnaam: `test_d3_unknown_network_failure_never_proposes_apply_or_trading_action`
  - doel: fail-closed op netwerkfout expliciet vastleggen
  - scenario: snapshot met `coinbase_call_succeeded=false` en `normalized_status=unknown`
  - expected result: `unknown_no_apply`, geen proposed mutation, geen trading recommendation
  - files likely to touch later: `tests/test_phase_d3_live_exit_reconciliation.py`, `tests/test_coinbase_order_snapshot.py`
  - live safety note: geen live client; pure snapshot fixtures

- voorgestelde testnaam: `test_d3_open_keep_open_preserves_order_counts_and_position_snapshot`
  - doel: hard bewijs dat `OPEN/open` geen state mutatie veroorzaakt
  - scenario: open snapshot met keep_open
  - expected result: order counts, reservation, position snapshot exact gelijk voor/na
  - files likely to touch later: `tests/test_phase_d3_live_exit_reconciliation.py`
  - live safety note: local fixture only

P1:

- voorgestelde testnaam: `test_d3_cancel_replace_governance_blocks_replace_until_cancelled_closeout_applied`
  - doel: cancel-first sequencing afdwingen
  - scenario: replace-candidate preview terwijl order nog open is
  - expected result: replace geblokkeerd, cancel-first required
  - files likely to touch later: `tests/test_phase_d3_cancel_replace_governance.py`, `tools/show_phase_d3_cancel_replace_governance.py`
  - live safety note: preview-only governance

- voorgestelde testnaam: `test_d3_cancel_replace_governance_blocks_when_replication_enabled`
  - doel: replication/follower isolation expliciet op cancel-only governance leggen
  - scenario: replication enabled in governance context
  - expected result: governance blocked / review required
  - files likely to touch later: `tests/test_phase_d3_cancel_replace_governance.py`, mogelijk `tools/show_function_preservation_audit.py`
  - live safety note: config-only, geen runtime

- voorgestelde testnaam: `test_d3_rejected_branch_preserves_no_new_sell_before_closeout_complete`
  - doel: expliciete post-reject safety vastleggen
  - scenario: rejected snapshot in existing lifecycle context
  - expected result: local finalization possible, maar geen new preview-submit readiness
  - files likely to touch later: `tests/test_phase_d3_live_exit_reconciliation.py`, `tests/test_phase_d3_rejected_submit_cleanup.py`
  - live safety note: no submit path

P2:

- voorgestelde testnaam: `test_d4_stale_thresholds_boundary_keep_open_vs_candidate`
  - doel: concrete stale-threshold grenswaarden vastleggen
  - scenario: order age en distance net onder en net boven drempels
  - expected result: deterministische transition keep_open -> candidate preview
  - files likely to touch later: `tests/test_phase_d3_open_exit_order_governance.py`, `tools/show_phase_d3_open_exit_order_governance.py`
  - live safety note: governance-only, geen cancel/replace

- voorgestelde testnaam: `test_d4_reservation_aware_replacement_requires_released_previous_reservation`
  - doel: replacement pas toestaan na coherente release
  - scenario: oude reservation nog aanwezig versus vrijgegeven
  - expected result: replacement blocked totdat release coherent is
  - files likely to touch later: `tests/test_phase_d3_cancel_replace_governance.py`, `tests/test_phase_d3_reservation_governance.py`
  - live safety note: design-only guard

- voorgestelde testnaam: `test_d4_trailing_preview_never_submits_and_respects_product_rules`
  - doel: toekomstige trailing design fail-closed houden
  - scenario: runner/trailing exit intent in D.4 preview
  - expected result: preview-only, no submit, product-rule rounding/report coherent
  - files likely to touch later: nieuwe D.4 tests, mogelijk `bot/phase_d2_position_executor.py` en latere D.4 module
  - live safety note: geen live pilot

- voorgestelde testnaam: `test_d4_logging_emits_cancel_first_observability_events`
  - doel: observability eisen vroeg vastleggen
  - scenario: cancel-candidate / replace-candidate preview
  - expected result: duidelijke audit/log fields zonder state mutation
  - files likely to touch later: toekomstige governance/report tools, `tests/test_function_preservation_audit.py`
  - live safety note: logging-only

P3:

- voorgestelde testnaam: `test_d5_learning_input_schema_requires_completed_exit_lifecycle`
  - doel: learning pas na complete exit events toestaan
  - scenario: incomplete versus complete lifecycle inputs
  - expected result: incomplete events blocked from learning-to-execution path
  - files likely to touch later: toekomstige D.5 modules/tests
  - live safety note: geen execution coupling

- voorgestelde testnaam: `test_d5_learning_never_changes_execution_without_separate_gate`
  - doel: harde scheiding tussen learning en execution
  - scenario: learned signal aanwezig zonder execution gate
  - expected result: observe-only / no live effect
  - files likely to touch later: toekomstige D.5 module, `tools/show_function_preservation_audit.py`
  - live safety note: safety-first invariant

## 7. What not to implement yet

- geen testimplementatie in deze ronde
- geen live-client tests
- geen state mutation
- geen codepatch
