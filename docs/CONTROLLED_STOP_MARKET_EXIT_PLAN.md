# Controlled Stop / Market Exit Plan

Report-only plan. This file does not authorize a cancel, market/IOC SELL, lifecycle apply, state repair, service restart or parameter change.

## Trigger

- Stop breach is evidenced by current position risk logic, exchange/order evidence or operator-provided UI evidence.
- Existing D.3 TP SELL is still open and stale above market.
- No second SELL may be submitted while the stale TP reservation remains open.

## Sequence

1. Freeze automation and collect read-only evidence only after an explicit trigger.
2. Verify local open order, linked position, reserved base, available base and duplicate/oversell status.
3. Cancel existing TP only after exact operator ACK for that specific order id.
4. Verify cancel using valid exchange evidence before preparing any market/IOC SELL.
5. Size market/IOC SELL from available base only, after subtracting any remaining reservations and respecting product increments/minimums.
6. Submit market/IOC SELL only after separate exact ACK for the final size and order mode.
7. Require fill evidence before local lifecycle apply.
8. Apply local fill only after separate exact ACK and evidence hash capture.

## Hard Stops

- Do not submit a second SELL before cancel verification.
- Do not sell more than available base.
- Do not infer fill from intent, logs or local status alone.
- Do not mutate `.env`, runtime config, parameters, state or orders without the matching ACK.
- Do not retry cancel/submit loops; one-shot action only, then reassess.
