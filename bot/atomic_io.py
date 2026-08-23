from __future__ import annotations

import json
import os
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


_PROCESS_LOCK_REGISTRY_GUARD = threading.RLock()
_ACTIVE_PROCESS_LOCKS: dict[str, dict[str, Any]] = {}

# Bestandsvergrendeling verschilt per platform: POSIX heeft fcntl.flock,
# Windows heeft msvcrt.locking. Beide geven dezelfde garantie die de runner
# nodig heeft -- een tweede proces kan de lock niet krijgen -- dus de
# aanroepende code hoeft het verschil niet te kennen.
_LOCK_BYTES = 1

# Vaste breedte voor de pid op Windows, zodat een kortere pid de vorige
# waarde volledig overschrijft zonder te truncaten.
_PID_FIELD_WIDTH = 20


class LockUnavailableError(Exception):
    """De lock wordt al door een ander proces gehouden."""


def _acquire_file_lock(handle) -> None:
    """Neem een exclusieve, niet-blokkerende lock op `handle`.

    Gooit LockUnavailableError als een ander proces de lock houdt.
    """
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, _LOCK_BYTES)
        except OSError as exc:
            raise LockUnavailableError from exc
        return

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise LockUnavailableError from exc


def _release_file_lock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, _LOCK_BYTES)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def unique_tmp_path(path: str | Path) -> Path:
    target = Path(path)
    return target.with_name(f"{target.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}")


def atomic_write_text(path: str | Path, text: str, *, encoding: str = "utf-8") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = unique_tmp_path(target)
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, target)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    return target


def atomic_write_json(path: str | Path, payload: Any, *, sort_keys: bool = True) -> Path:
    return atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=sort_keys) + "\n",
    )


def runtime_mutation_lock_path(*, cfg: Any = None, order_store: Any = None) -> Path:
    """Return the single runtime-wide lock path without touching state."""
    configured = str(
        os.getenv("RUN_TRADER_LOOP_LOCK_PATH")
        or getattr(cfg, "runtime_mutation_lock_path", "")
        or ""
    ).strip()
    if configured:
        return Path(configured)
    store_path = getattr(order_store, "path", None)
    if store_path:
        return Path(store_path).parent / "runtime_mutation.lock"
    return Path("state/runtime_mutation.lock")


@contextmanager
def process_lock(path: str | Path, *, allow_reentrant: bool = False) -> Iterator[dict[str, Any]]:
    """Acquire a non-blocking process lock.

    The default intentionally rejects nested acquisition, including within the
    same process. A mutating sub-boundary may opt into reentrancy only when it
    runs on the same thread as an already locked runtime boundary. That lets
    lifecycle apply work share the runner lock without weakening the normal
    duplicate-run guard.
    """
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_path = str(lock_path.resolve())
    pid = os.getpid()
    thread_id = threading.get_ident()
    reentrant = False

    with _PROCESS_LOCK_REGISTRY_GUARD:
        active = _ACTIVE_PROCESS_LOCKS.get(canonical_path)
        if active is not None:
            if (
                allow_reentrant
                and active.get("pid") == pid
                and active.get("thread_id") == thread_id
            ):
                active["depth"] = int(active.get("depth", 1)) + 1
                reentrant = True
            else:
                raise RuntimeError(
                    f"process_lock_already_active:{lock_path}:pid={active.get('pid', 'unknown')}"
                )
        else:
            _ACTIVE_PROCESS_LOCKS[canonical_path] = {
                "pid": pid,
                "thread_id": thread_id,
                "depth": 1,
                "fh": None,
            }

    if reentrant:
        try:
            yield {
                "path": str(lock_path),
                "pid": pid,
                "acquired": True,
                "reentrant": True,
            }
        finally:
            with _PROCESS_LOCK_REGISTRY_GUARD:
                active = _ACTIVE_PROCESS_LOCKS.get(canonical_path)
                if active is not None:
                    active["depth"] = int(active.get("depth", 1)) - 1
        return

    try:
        fh = lock_path.open("a+", encoding="utf-8")
    except Exception:
        with _PROCESS_LOCK_REGISTRY_GUARD:
            _ACTIVE_PROCESS_LOCKS.pop(canonical_path, None)
        raise
    acquired = False
    try:
        try:
            _acquire_file_lock(fh)
        except LockUnavailableError as exc:
            fh.seek(0)
            existing = fh.read().strip()
            raise RuntimeError(f"process_lock_already_active:{lock_path}:pid={existing or 'unknown'}") from exc
        acquired = True
        fh.seek(0)
        if os.name != "nt":
            # Op Windows valt de vergrendelde byte binnen het bestand; die
            # wegtruncaten zou de lock onder onze eigen voeten verwijderen.
            # De pid wordt daar met vaste breedte overschreven in plaats van
            # het bestand te legen.
            fh.truncate()
            fh.write(str(pid))
        else:
            fh.write(str(pid).ljust(_PID_FIELD_WIDTH))
        fh.flush()
        with _PROCESS_LOCK_REGISTRY_GUARD:
            active = _ACTIVE_PROCESS_LOCKS.get(canonical_path)
            if active is not None:
                active["fh"] = fh
        yield {"path": str(lock_path), "pid": pid, "acquired": True, "reentrant": False}
    finally:
        try:
            if acquired:
                fh.seek(0)
                if os.name != "nt":
                    fh.truncate()
                _release_file_lock(fh)
        finally:
            fh.close()
            with _PROCESS_LOCK_REGISTRY_GUARD:
                _ACTIVE_PROCESS_LOCKS.pop(canonical_path, None)


__all__ = [
    "atomic_write_json",
    "atomic_write_text",
    "process_lock",
    "runtime_mutation_lock_path",
    "unique_tmp_path",
]
