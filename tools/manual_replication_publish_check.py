#!/usr/bin/env python3
"""Handmatige replicatiecheck; stuurt een testenvelope naar de replica.

Heette test_replication_publish.py in de projectroot. Die naam liet pytest
het bestand verzamelen, waar het botste met de echte test met dezelfde naam
in tests/. Dit is geen test maar een diagnosescript: het draait alleen via
__main__ en bevat geen testfuncties.
"""
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