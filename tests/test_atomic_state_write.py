from __future__ import annotations

import json
import threading

from bot.atomic_io import atomic_write_json, unique_tmp_path


def test_atomic_write_uses_unique_tmp_names(tmp_path) -> None:
    path = tmp_path / "file.json"
    assert unique_tmp_path(path) != unique_tmp_path(path)


def test_parallel_atomic_writes_do_not_raise_filenotfound(tmp_path) -> None:
    path = tmp_path / "state.json"
    errors = []

    def write_one(i: int) -> None:
        try:
            atomic_write_json(path, {"i": i})
        except FileNotFoundError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=write_one, args=(i,)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert isinstance(json.loads(path.read_text(encoding="utf-8")), dict)
