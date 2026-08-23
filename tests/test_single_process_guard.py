from __future__ import annotations

from datetime import datetime, timezone
import os
import subprocess
import sys

import pytest

from bot.atomic_io import process_lock
from bot.run_cycle_guard import CycleBoundaryGuard


def test_second_runner_lock_is_blocked(tmp_path) -> None:
    lock_path = tmp_path / "runner.lock"
    with process_lock(lock_path):
        with pytest.raises(RuntimeError, match="process_lock_already_active"):
            with process_lock(lock_path):
                pass


def test_explicit_same_thread_reentrant_lock_is_allowed(tmp_path) -> None:
    lock_path = tmp_path / "runner.lock"
    with process_lock(lock_path) as outer:
        with process_lock(lock_path, allow_reentrant=True) as nested:
            assert outer["reentrant"] is False
            assert nested["reentrant"] is True


def test_second_process_cannot_clear_lock_holder_pid(tmp_path) -> None:
    lock_path = tmp_path / "runner.lock"
    child = (
        "from bot.atomic_io import process_lock\n"
        f"path = {str(lock_path)!r}\n"
        "try:\n"
        "    with process_lock(path):\n"
        "        raise SystemExit('unexpected_lock_acquisition')\n"
        "except RuntimeError as exc:\n"
        "    print(str(exc))\n"
    )

    with process_lock(lock_path):
        result = subprocess.run(
            [sys.executable, "-c", child],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "process_lock_already_active" in result.stdout
        assert lock_path.read_text(encoding="utf-8") == str(os.getpid())


def test_duplicate_cycle_boundary_is_skipped(tmp_path) -> None:
    guard = CycleBoundaryGuard(tmp_path / "cycles.json")
    now = datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc)

    assert guard.should_run("full", now) is True
    assert guard.should_run("full", now) is False
    assert guard.should_run("heartbeat", now) is True
