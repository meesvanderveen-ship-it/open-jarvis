# Codex Prompt Templates

Use these short templates with `AGENTS.md` and `docs/CODEX_WORKFLOW.md` as the standing instructions.

## 1. D.3 Monitor Trigger Check

```text
Volg AGENTS.md en docs/CODEX_WORKFLOW.md.
Taak: bepaal of er een trigger is voor de actieve D.3 TP1 SELL.
Geen trigger = geen Coinbase poll.
Trigger = exact een read-only lifecycle poll.
Geen live action, geen state write.
```

## 2. D.3 Lifecycle Apply on Fill Evidence

```text
Volg AGENTS.md en docs/CODEX_WORKFLOW.md.
Taak: bereid Controlled D.3 Lifecycle Apply on Fill Evidence v1 voor op basis van PARTIAL/FILLED evidence.
Geen apply zonder exacte ACK.
Geen cancel/replace/submit.
```

## 3. D.3 Terminal Closeout Reconcile

```text
Volg AGENTS.md en docs/CODEX_WORKFLOW.md.
Taak: bereid Controlled D.3 Terminal Closeout Reconcile v1 voor op basis van CANCELLED/EXPIRED/REJECTED evidence.
Geen apply zonder exacte ACK.
Position blijft open tenzij fill/plan anders vereist.
```

## 4. D.3 Reprice Decision

```text
Volg AGENTS.md en docs/CODEX_WORKFLOW.md.
Taak: beoordeel reprice-opties A/B/C voor actieve D.3 TP1.
Decision-only tenzij exact approval + one-shot ACK aanwezig.
Geen live action zonder approval.
```

## 5. D.3 Cancel/Replace Reprice

```text
Volg AGENTS.md en docs/CODEX_WORKFLOW.md.
Taak: voer Controlled D.3 Exit Cancel/Replace Reprice uit voor exact gekozen optie.
Cancel-first.
Replacement alleen na confirmed cancel.
Exact een poging.
Geen retry-storm.
```

## 6. D.4 Design

```text
Volg AGENTS.md en docs/CODEX_WORKFLOW.md.
Taak: ontwerp D.4 trailing/cancel-replace automation read-only/scaffold-only.
Geen live automation.
Geen live cancel/replace.
Geen state writes behalve docs/tests.
```

## 7. D.4/D.5 GitHub Research Spike

```text
Volg AGENTS.md en docs/CODEX_WORKFLOW.md.
Taak: voer D.4/D.5 GitHub/open-source research uit.
Maak/werk docs bij met source matrix, licenties, trailing/cancel-first/cooldown/slippage/fill quality/no-fill patronen.
Geen Coinbase calls.
Geen live action.
Geen dependency toevoegen.
Geen externe code copy-pasten zonder licentiebeoordeling.
```

## 8. D.4 Trailing Preview Scaffold

```text
Volg AGENTS.md en docs/CODEX_WORKFLOW.md.
Taak: bouw D.4 trailing preview scaffold met fake snapshots en temp dirs.
Alleen preview: trailing activation, peak/reference price, proposed replacement candidate, product-rule blockers.
Cancel-first blijft verplicht.
Geen live cancel/replace/submit.
Geen trading-state write.
```

## 9. D.5 Execution Metrics Scaffold

```text
Volg AGENTS.md en docs/CODEX_WORKFLOW.md.
Taak: bouw D.5 execution metrics scaffold analysis-only.
Meet slippage, fill quality, no-fill duration, fees, latency en realized-vs-planned edge uit complete lifecycle events.
Blokkeer learning-to-execution zonder aparte gate en ACK.
Geen live action.
Geen trading-state write.
```

## 10. D.4 Dry-Run Cancel/Replace Planner

```text
Volg AGENTS.md en docs/CODEX_WORKFLOW.md.
Taak: bouw D.4 dry-run cancel/replace planner bovenop trailing preview.
Alleen dry-run: cancel-first outline, replacement pas na confirmed cancel, future ACK required.
Geen Coinbase calls.
Geen live cancel/replace/submit.
Geen trading-state write.
```

## 11. D.4 Reprice Decision

```text
Volg AGENTS.md en docs/CODEX_WORKFLOW.md.
Taak: maak D.4 reprice decision report voor actieve D.3 exit.
Vergelijk keep, plan-preserving, recovery targets en near-market de-risk.
Decision-only.
Geen cancel/replace/submit.
Geen lifecycle apply.
Geen trading-state write.
```

## 12. D.4/D.5 Operator Decision Report

```text
Volg AGENTS.md en docs/CODEX_WORKFLOW.md.
Taak: bouw of toon D.4/D.5 operator decision report.
Combineer D.3 lifecycle, D.4 preview/planner en D.5 metrics tot één report-only aanbeveling.
Geen Coinbase calls.
Geen live action.
Geen lifecycle apply.
Geen learning-to-execution.
```

## 13. D.45 Real-State Read-Only Operator Report

```text
Volg AGENTS.md en docs/CODEX_WORKFLOW.md.
Taak: toon D.45 real-state read-only operator report voor de actieve D.3 exit.
Lees alleen lokale statebestanden.
Geen Coinbase calls.
Geen live action.
Geen lifecycle apply.
Geen trading-state write.
P0 blockers overrulen D.4/D.5 signalen.
```

## 14. D.3 Reservation Drift Repair Preview

```text
Volg AGENTS.md en docs/CODEX_WORKFLOW.md.
Taak: diagnoseer D.3 reservation drift en maak guarded repair-preview.
Preview-only tenzij exacte ACK aanwezig is.
Geen Coinbase calls.
Geen live action.
Geen lifecycle apply.
Geen echte trading-state write zonder ACK.
```

## 15. D.45 Trigger-Aware Operator Cycle

```text
Volg AGENTS.md en docs/CODEX_WORKFLOW.md.
Taak: maak D.45 trigger-aware operator cycle report.
Check eerst lokale D.45/P0 state.
Lifecycle poll maximaal één keer read-only als trigger-policy dat rechtvaardigt.
Beoordeel reprice-readiness decision-only.
Geen live action.
Geen lifecycle apply.
Geen trading-state write.
```

## 16. D.4 Controlled Replacement Submit Gate Integration

```text
Volg AGENTS.md en docs/CODEX_WORKFLOW.md.
Taak: bouw of valideer D.4 controlled replacement submit gate integration.
Maak alleen de centrale live-exit gate geschikt voor source phase_d4_controlled_cancel_replace.
Vereis exacte ACK en process-local one-shot arming.
Geen Coinbase write calls.
Geen live cancel/replace/submit.
Geen lifecycle apply.
Geen trading-state write buiten tmp_path tests.
Geen .env-mutatie.
```

## 17. Safety Incident Recovery

```text
Volg AGENTS.md en docs/CODEX_WORKFLOW.md.
Taak: diagnoseer safety incident.
Geen live action.
Geen state mutation tenzij aparte recovery ACK.
Rapporteer P0/P1 en minimale recoveryroute.
```
