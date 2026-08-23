import json

from dashboard.backend.services import reports as reports_service


def test_list_reports_discovers_files_within_depth(tmp_path, monkeypatch):
    monkeypatch.setattr(reports_service.config, "REPORTS_ROOT", tmp_path)
    (tmp_path / "audits").mkdir()
    (tmp_path / "audits" / "foo-latest.json").write_text("{}")
    (tmp_path / "audits" / "foo-latest.md").write_text("# hi")
    deep_dir = tmp_path / "reflection" / "snapshots"
    deep_dir.mkdir(parents=True)
    (deep_dir / "deep.json").write_text("{}")
    (tmp_path / "audits" / "ignored.txt").write_text("nope")

    entries = reports_service.list_reports()
    ids = {e["id"] for e in entries}

    assert "audits/foo-latest.json" in ids
    assert "audits/foo-latest.md" in ids
    assert not any("snapshots" in i for i in ids), "deep files must be excluded by depth cap"
    assert not any(i.endswith(".txt") for i in ids)


def test_get_report_returns_parsed_json(tmp_path, monkeypatch):
    monkeypatch.setattr(reports_service.config, "REPORTS_ROOT", tmp_path)
    (tmp_path / "audits").mkdir()
    payload = {"hello": "world"}
    (tmp_path / "audits" / "foo-latest.json").write_text(json.dumps(payload))

    result = reports_service.get_report("audits/foo-latest.json")

    assert result["content"] == payload
    assert result["truncated"] is False


def test_get_report_rejects_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(reports_service.config, "REPORTS_ROOT", tmp_path / "reports")
    (tmp_path / "reports").mkdir()
    (tmp_path / "secret.json").write_text("{}")

    import pytest

    with pytest.raises(FileNotFoundError):
        reports_service.get_report("../secret.json")


def test_get_report_caps_oversized_files(tmp_path, monkeypatch):
    monkeypatch.setattr(reports_service.config, "REPORTS_ROOT", tmp_path)
    monkeypatch.setattr(reports_service.config, "MAX_INLINE_BYTES", 10)
    (tmp_path / "audits").mkdir()
    (tmp_path / "audits" / "big-latest.json").write_text(json.dumps({"x": "y" * 100}))

    result = reports_service.get_report("audits/big-latest.json")

    assert result["truncated"] is True
    assert result["content"] is None
