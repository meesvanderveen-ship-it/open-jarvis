import pytest

from dashboard.backend.security.safe_paths import (
    UnsafePathError,
    resolve_state_file,
    resolve_under_logs,
    resolve_under_reports,
)


def test_allowed_state_file_resolves():
    path = resolve_state_file("positions.json")
    assert path.name == "positions.json"


def test_disallowed_state_file_is_rejected():
    with pytest.raises(UnsafePathError):
        resolve_state_file("positions.json.backup-before-eth-restore-20260509-151228")


def test_env_file_is_always_rejected_even_if_relative_path_tries_to_reach_it():
    with pytest.raises(UnsafePathError):
        resolve_state_file(".env")


def test_traversal_out_of_reports_root_is_rejected():
    with pytest.raises(UnsafePathError):
        resolve_under_reports("../.env")


def test_traversal_out_of_logs_root_is_rejected():
    with pytest.raises(UnsafePathError):
        resolve_under_logs("../../.env")


def test_normal_report_relative_path_resolves_within_root():
    from dashboard.backend import config

    path = resolve_under_reports("audits")
    assert str(path).startswith(str(config.REPORTS_ROOT.resolve()))
