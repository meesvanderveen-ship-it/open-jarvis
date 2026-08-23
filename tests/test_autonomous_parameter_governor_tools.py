from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, *args], cwd=cwd, text=True, capture_output=True, check=True)


def test_governor_tools_default_noop_on_missing_candidate(tmp_path: Path) -> None:
    (tmp_path / "state").mkdir(parents=True)
    (tmp_path / "state/open_orders.json").write_text('{"orders": {}}\n', encoding="utf-8")
    (tmp_path / "state/positions.json").write_text("{}\n", encoding="utf-8")
    status = json.loads(_run(["tools/show_autonomous_parameter_governor_status.py", "--json", "--root", str(tmp_path)]).stdout)
    assert status["can_authorize_orders"] is False
    assert status["can_mutate_allowed_parameters"] is False
    assert status["reason"] == "candidate_file_missing"
    plan = json.loads(_run(["tools/prepare_autonomous_parameter_activation.py", "--json", "--root", str(tmp_path)]).stdout)
    assert plan["activation_plan_available"] is False
    run = json.loads(_run(["tools/run_autonomous_parameter_governor.py", "--json", "--root", str(tmp_path)]).stdout)
    assert run["applied"] is False
    assert run["state_write_performed"] is False
    audit = json.loads(_run(["tools/write_autonomous_parameter_governor_audit.py", "--json", "--root", str(tmp_path)]).stdout)
    assert audit["safety_policy"]["no_coinbase_actions"] is True
    assert audit["safety_policy"]["no_env_mutation"] is True


def test_rollback_tool_default_dry_run(tmp_path: Path) -> None:
    result = json.loads(_run(["tools/rollback_autonomous_parameter_profile.py", "--json", "--root", str(tmp_path)]).stdout)
    assert result["applied"] is False
    assert result["env_mutation_performed"] is False


def test_governor_timer_templates_exist_and_use_locking_runner() -> None:
    service = ROOT / "deploy_templates/coinbase-reflection-adaptive-governor.service"
    timer = ROOT / "deploy_templates/coinbase-reflection-adaptive-governor.timer"
    assert service.exists()
    assert timer.exists()
    service_text = service.read_text(encoding="utf-8")
    assert "tools/run_autonomous_parameter_governor.py --json" in service_text
    assert "No Coinbase order submit/cancel/apply authority" in service_text
    assert "OnUnitActiveSec=1h" in timer.read_text(encoding="utf-8")


def test_env_configuration_tool_only_changes_allowlisted_keys(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("EXECUTION_MODE=live\nENABLE_MARKET_ORDERS=true\n", encoding="utf-8")
    result = json.loads(_run(["tools/configure_autonomous_parameter_governor_env.py", "--json", "--apply", "--root", str(tmp_path)]).stdout)
    assert result["applied"] is True
    assert result["forbidden_keys_changed"] == []
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "EXECUTION_MODE=live" in text
    assert "ENABLE_MARKET_ORDERS=true" in text
    assert "ENABLE_AUTONOMOUS_PARAMETER_GOVERNOR=true" in text
    assert "AUTONOMOUS_PARAMETER_GOVERNOR_MODE=apply_when_safe" in text
    assert Path(result["backup_path"]).exists()
    assert Path(result["approved_profile_backup_path"]).exists()
