from __future__ import annotations

from pathlib import Path

from bot.phase_follower_receiver_api_audit import (
    build_follower_receiver_api_audit_report,
    render_follower_receiver_api_audit_markdown,
)


def _write_receiver(path: Path, text: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    file_path = path / "receiver.py"
    file_path.write_text(text, encoding="utf-8")
    return file_path


def _basic_receiver_text(*, hmac: bool = True, lifecycle: bool = True, live_default: bool = False) -> str:
    hmac_block = (
        "import hmac\n"
        "def verify_signature(body, signature):\n"
        "    return hmac.compare_digest(signature, 'ok')\n"
        "SIGNATURE_HEADER = 'x-replica-signature'\n"
        if hmac
        else ""
    )
    lifecycle_route = (
        "@app.post('/api/replica/lifecycle')\n"
        "def lifecycle(event):\n"
        "    if event.get('schema_version') != 'replication.lifecycle.v1':\n"
        "        raise HTTPException(status_code=400, detail='unknown_event_fail_closed')\n"
        "    phase = event.get('phase')\n"
        "    if phase in ('D3', 'D4'):\n"
        "        return {'effect': 'observe_only'}\n"
        "    if phase in ('C4', 'D1', 'D2', 'D5', 'governance'):\n"
        "        return {'effect': 'paper_only'}\n"
        "    raise HTTPException(status_code=400, detail='unsupported')\n"
        if lifecycle
        else ""
    )
    live_line = "FOLLOWER_LIVE_MODE = True\n" if live_default else "FOLLOWER_LIVE_MODE = False\n"
    return (
        "from fastapi import FastAPI, HTTPException\n"
        f"{hmac_block}"
        "app = FastAPI()\n"
        f"{live_line}"
        "PAPER_MODE_DEFAULT = True\n"
        "LIVE_ACK_REQUIRED = True\n"
        "def check_buy(event):\n"
        "    product_rule = event['product_rule']; balance = event['balance']; cap = event['max_notional_cap']\n"
        "    min_size = event['min_size']; base_increment = event['base_increment']; quote_increment = event['quote_increment']\n"
        "    event_id = event['event_id']; idempotency_store = event_id; drift_reconcile = True\n"
        "    return product_rule and balance and cap and min_size and base_increment and quote_increment and idempotency_store and drift_reconcile\n"
        "def check_sell(event):\n"
        "    no_oversell = event['available_base'] >= event['reduce_size']; reduce_only = True\n"
        "    reservation = event['reserved_base_open_exit_orders']; open_exit = event.get('open_exit')\n"
        "    drift_reconcile = True; sell_ack = event['sell_ack']\n"
        "    return no_oversell and reduce_only and reservation is not None and open_exit is not None and drift_reconcile and sell_ack\n"
        "@app.post('/api/replica/decision')\n"
        "def decision(event):\n"
        "    nonce = event.get('nonce'); replay_window = event.get('timestamp')\n"
        "    return {'mode': 'paper', 'nonce': nonce, 'replay_window': replay_window}\n"
        f"{lifecycle_route}"
    )


def test_follower_code_absent_is_watch_and_not_live_ready(tmp_path: Path) -> None:
    report = build_follower_receiver_api_audit_report(root=tmp_path, follower_paths=[tmp_path / "missing"])

    assert report["classification"] == "WATCH"
    flags = report["readiness_flags"]
    assert flags["follower_receiver_code_accessible"] is False
    assert flags["follower_ready_for_live"] is False
    assert flags["follower_buy_ready"] is False
    assert flags["follower_sell_ready"] is False
    assert "follower_receiver_code_not_accessible" in report["blockers"]


def test_receiver_endpoint_present_fixture_summarizes_endpoints(tmp_path: Path) -> None:
    follower = tmp_path / "coinbase-replica"
    _write_receiver(follower, _basic_receiver_text())

    report = build_follower_receiver_api_audit_report(root=tmp_path, follower_paths=[follower])

    endpoints = report["endpoint_audit"]
    assert report["readiness_flags"]["follower_receiver_code_accessible"] is True
    assert endpoints["decision_endpoint_status"] == "present"
    assert endpoints["lifecycle_endpoint_status"] == "present"
    assert "/api/replica/decision" in endpoints["endpoints_found"]
    assert "/api/replica/lifecycle" in endpoints["endpoints_found"]


def test_missing_hmac_is_blocker(tmp_path: Path) -> None:
    follower = tmp_path / "coinbase-replica"
    _write_receiver(follower, _basic_receiver_text(hmac=False))

    report = build_follower_receiver_api_audit_report(root=tmp_path, follower_paths=[follower])

    assert report["auth_hmac_audit"]["hmac_required"] is False
    assert "hmac_signature_verification_not_proven" in report["blockers"]
    assert report["readiness_flags"]["follower_ready_for_live"] is False


def test_live_mode_default_enabled_is_stop_now(tmp_path: Path) -> None:
    follower = tmp_path / "coinbase-replica"
    _write_receiver(follower, _basic_receiver_text(live_default=True))

    report = build_follower_receiver_api_audit_report(root=tmp_path, follower_paths=[follower])

    assert report["classification"] == "STOP_NOW"
    assert report["mode_separation"]["unsafe_live_default_detected"] is True
    assert "unsafe_follower_live_default_enabled" in report["blockers"]


def test_decision_only_receiver_has_no_lifecycle_parity(tmp_path: Path) -> None:
    follower = tmp_path / "coinbase-replica"
    _write_receiver(follower, _basic_receiver_text(lifecycle=False))

    report = build_follower_receiver_api_audit_report(root=tmp_path, follower_paths=[follower])

    assert report["endpoint_audit"]["decision_endpoint_status"] == "present"
    assert report["endpoint_audit"]["lifecycle_endpoint_status"] == "missing"
    assert report["readiness_flags"]["lifecycle_parity_ready"] is False
    assert "lifecycle_endpoint_missing" in report["blockers"]


def test_buy_and_sell_readiness_stay_false_without_required_checks(tmp_path: Path) -> None:
    follower = tmp_path / "coinbase-replica"
    _write_receiver(
        follower,
        "from fastapi import FastAPI\n"
        "import hmac\n"
        "app = FastAPI()\n"
        "SIGNATURE_HEADER = 'x-replica-signature'\n"
        "def verify_signature(body, sig): return hmac.compare_digest(sig, 'ok')\n"
        "@app.post('/api/replica/decision')\n"
        "def decision(event): return {'event_id': event.get('event_id'), 'paper': True, 'ack': False}\n"
        "@app.post('/api/replica/lifecycle')\n"
        "def lifecycle(event): return {'schema_version': 'replication.lifecycle.v1', 'observe': True}\n",
    )

    report = build_follower_receiver_api_audit_report(root=tmp_path, follower_paths=[follower])

    assert report["buy_readiness"]["follower_buy_ready"] is False
    assert report["sell_readiness"]["follower_sell_ready"] is False
    assert any(blocker.startswith("buy_check_missing:") for blocker in report["blockers"])
    assert any(blocker.startswith("sell_check_missing:") for blocker in report["blockers"])


def test_no_http_calls_and_no_state_writes_are_reported(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    open_orders = state / "open_orders.json"
    open_orders.write_text('{"orders": {}}', encoding="utf-8")

    before = open_orders.read_text(encoding="utf-8")
    report = build_follower_receiver_api_audit_report(root=tmp_path, follower_paths=[tmp_path / "missing"])

    metadata = report["metadata"]
    assert metadata["http_call_attempted"] is False
    assert metadata["coinbase_call_attempted"] is False
    assert metadata["state_write_performed"] is False
    assert open_orders.read_text(encoding="utf-8") == before


def test_markdown_contains_required_readiness_flags(tmp_path: Path) -> None:
    report = build_follower_receiver_api_audit_report(root=tmp_path, follower_paths=[tmp_path / "missing"])
    markdown = render_follower_receiver_api_audit_markdown(report)

    assert "follower_receiver_code_accessible" in markdown
    assert "follower_ready_for_live" in markdown
    assert "Remote Audit Checklist" in markdown
