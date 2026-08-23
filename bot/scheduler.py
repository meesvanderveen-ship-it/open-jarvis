from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone


def _next_interval_boundary(now: datetime, interval_hours: int, second_offset: int = 5) -> datetime:
    if interval_hours <= 0:
        raise ValueError("interval_hours moet > 0 zijn")
    if 24 % interval_hours != 0:
        raise ValueError("interval_hours moet een deler van 24 zijn")

    next_hour_block = ((now.hour // interval_hours) + 1) * interval_hours
    if next_hour_block >= 24:
        return (now + timedelta(days=1)).replace(
            hour=0,
            minute=0,
            second=second_offset,
            microsecond=0,
        )
    return now.replace(
        hour=next_hour_block,
        minute=0,
        second=second_offset,
        microsecond=0,
    )


def seconds_until_next_interval_boundary(
    interval_hours: int = 4,
    second_offset: int = 5,
) -> float:
    now = datetime.now(timezone.utc)
    target = _next_interval_boundary(
        now,
        interval_hours=interval_hours,
        second_offset=second_offset,
    )
    return max(0.0, (target - now).total_seconds())


def sleep_until_next_interval_boundary(interval_hours: int = 4, second_offset: int = 5) -> None:
    seconds = seconds_until_next_interval_boundary(
        interval_hours=interval_hours,
        second_offset=second_offset,
    )
    if seconds > 0:
        time.sleep(seconds)


def sleep_until_next_4h_boundary() -> None:
    sleep_until_next_interval_boundary(interval_hours=4, second_offset=5)