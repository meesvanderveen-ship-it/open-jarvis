from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_c4_d1_handoff_branch_map import (  # noqa: E402
    PHASE,
    build_c4_d1_handoff_branch_map,
    render_c4_d1_handoff_branch_map_markdown,
)
from bot.phase_c45_live_fill_pilot import C45_FILL_APPLY_ACK  # noqa: E402
from tools.build_c4_d1_handoff_branch_map import main  # noqa: E402


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _root(tmp_path: Path, *, orders: dict[str, dict] | None = None, btc_position: dict | None = None) -> Path:
    _write(tmp_path / "state/open_orders.json", {"orders": orders or {}})
    _write(
        tmp_path / "state/positions.json",
        {
            "BTC-USDC": {
                "position_size_base": "0",
                "bot_managed_base": "0",
                "reserved_base_open_exit_orders": "0",
                "monitoring_enabled": False,
                **(btc_position or {}),
            }
        },
    )
    (tmp_path / "reports/d6").mkdir(parents=True)
    return tmp_path


def _c4_order(status: str, *, client_order_id: str = "phasec-BTCUSDC-test", extra: dict | None = None) -> dict:
    return {
        "client_order_id": client_order_id,
        "exchange_order_id": "exchange-1",
        "ticker": "BTC-USDC",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "mode": "live",
        "execution_action": "place_limit_buy",
        "opened_via_phase_c43": True,
        "source_mode": "autonomous_small_live",
        "status": status,
        **(extra or {}),
    }


def test_no_order_branch_is_ok_and_report_only(tmp_path: Path) -> None:
    root = _root(tmp_path)
    before_open = (root / "state/open_orders.json").read_text(encoding="utf-8")
    before_positions = (root / "state/positions.json").read_text(encoding="utf-8")

    report = build_c4_d1_handoff_branch_map(root=root)

    assert report["phase"] == PHASE
    assert report["current_branch"]["branch_id"] == "A"
    assert report["current_branch"]["status"] == "OK"
    assert report["no_coinbase_call"] is True
    assert report["state_write_performed"] is False
    assert (root / "state/open_orders.json").read_text(encoding="utf-8") == before_open
    assert (root / "state/positions.json").read_text(encoding="utf-8") == before_positions


def test_open_order_branch_is_watch(tmp_path: Path) -> None:
    root = _root(tmp_path, orders={"phasec-BTCUSDC-test": _c4_order("submitted")})

    report = build_c4_d1_handoff_branch_map(root=root)

    assert report["current_branch"]["branch_id"] == "B"
    assert report["current_branch"]["status"] == "WATCH"
    assert report["current_state_evidence"]["order_summary"]["open_c4_entry_order_count"] == 1


def test_filled_branch_requires_c45_ack_and_separates_d3_preview_from_live_exit(tmp_path: Path) -> None:
    root = _root(tmp_path, orders={"phasec-BTCUSDC-test": _c4_order("filled", extra={"filled_size": "0.0001"})})

    report = build_c4_d1_handoff_branch_map(root=root, include_terminal_c4_handoff=True)
    branches = {branch["branch_id"]: branch for branch in report["branches"]}

    assert report["current_branch"]["branch_id"] == "F"
    assert report["current_branch"]["status"] == "WATCH"
    assert C45_FILL_APPLY_ACK in branches["F"]["ack_required_before_progression"]
    assert report["operator_conclusion"]["d2_d3_preview_is_not_live_exit_permission"] is True
    assert any("D3 live exit submit" in item for item in branches["F"]["forbidden_actions_without_separate_exact_ack"])


def test_inconsistent_duplicate_open_order_is_stop_now(tmp_path: Path) -> None:
    root = _root(
        tmp_path,
        orders={
            "one": _c4_order("submitted", client_order_id="phasec-BTCUSDC-one"),
            "two": _c4_order("submitted", client_order_id="phasec-BTCUSDC-two"),
        },
    )

    report = build_c4_d1_handoff_branch_map(root=root)

    assert report["current_branch"]["branch_id"] == "G"
    assert report["current_branch"]["status"] == "STOP_NOW"
    assert "multiple_open_c4_entry_orders" in report["current_branch"]["reasons"]


def test_d3_preview_never_implies_live_exit_permission_in_markdown(tmp_path: Path) -> None:
    report = build_c4_d1_handoff_branch_map(root=_root(tmp_path))
    markdown = render_c4_d1_handoff_branch_map_markdown(report)

    assert "# C4/D1 Handoff Branch Map" in markdown
    assert "D2/D3 preview is not live exit permission" in markdown
    assert "submit_live=False" in markdown
    assert "Branch G - inconsistent_evidence" in markdown


def test_cli_writes_reports_d6_only_and_no_state(tmp_path: Path, monkeypatch) -> None:
    root = _root(tmp_path)
    before_open = (root / "state/open_orders.json").read_text(encoding="utf-8")
    before_positions = (root / "state/positions.json").read_text(encoding="utf-8")
    monkeypatch.chdir(root)

    rc = main(
        [
            "--json-out",
            "reports/d6/c4-d1-handoff.json",
            "--markdown-out",
            "reports/d6/c4-d1-handoff.md",
        ]
    )

    assert rc == 0
    payload = json.loads((root / "reports/d6/c4-d1-handoff.json").read_text(encoding="utf-8"))
    markdown = (root / "reports/d6/c4-d1-handoff.md").read_text(encoding="utf-8")
    assert payload["phase"] == PHASE
    assert "C4/D1 Handoff Branch Map" in markdown
    assert (root / "state/open_orders.json").read_text(encoding="utf-8") == before_open
    assert (root / "state/positions.json").read_text(encoding="utf-8") == before_positions
