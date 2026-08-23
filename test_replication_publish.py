#!/usr/bin/env python3
from __future__ import annotations

from replication.publisher import ReplicaPublisher


def main() -> None:
    publisher = ReplicaPublisher()

    envelope = publisher.build_envelope(
        ticker="ETH-USDC",
        decision="approve_trade",
        side="BUY",
        strategy="trend_continuation",
        setup_type="trend_continuation",
        confidence=81,
        requested_size_quote=25.0,
        reason_summary=[
            "4h trend constructive",
            "1h pullback held support",
        ],
        must_reject_if=[
            "spread too wide",
            "support lost",
        ],
        analysis={"source": "server1-test"},
        metadata={"origin": "manual_test"},
    )

    result = publisher.publish(envelope)
    print(result)


if __name__ == "__main__":
    main()