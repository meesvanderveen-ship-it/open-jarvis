"""Canonical local entrypoint: `python -m dashboard.backend.run`.

Refuses to bind off-loopback unless DASHBOARD_ALLOW_NON_LOOPBACK=true is set
explicitly — this dashboard is meant to be reached only via an SSH tunnel.
"""

from __future__ import annotations

import sys

import uvicorn

from dashboard.backend import config

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def main() -> None:
    if config.HOST not in LOOPBACK_HOSTS and not config.ALLOW_NON_LOOPBACK:
        print(
            f"Refusing to bind {config.HOST}: not a loopback address and "
            "DASHBOARD_ALLOW_NON_LOOPBACK is not set. This dashboard is "
            "read-only but still meant to be local-only by default.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    uvicorn.run("dashboard.backend.app:app", host=config.HOST, port=config.PORT, reload=False)


if __name__ == "__main__":
    main()
