"""Shell out to the project's existing read-only `tools/show_*.py` scripts.

These scripts already self-report `read_only`/`state_write_performed`/
`coinbase_call_attempted`/`service_restart_attempted` flags in their own
JSON output, and are the vetted source of truth for live/pipeline/learning
status. We never reimplement their logic — only invoke them with a fixed
argv (no shell, no string interpolation of any request input) and parse
stdout as JSON.
"""

from __future__ import annotations

import json
import subprocess

from dashboard.backend import config


class ToolExecutionError(RuntimeError):
    pass


def run_json_tool(script_name: str, extra_args: list[str] | None = None) -> dict:
    """Run `python -m tools.<module> --json [extra_args]` and parse stdout as JSON.

    `script_name` and `extra_args` must never be derived from request input —
    callers pass fixed, hardcoded values only. Invoked as `-m tools.<module>`
    (not as a bare script path) because these scripts import `bot.*` using
    plain `from bot.x import y`, which only resolves when the project root
    is on sys.path — which `-m` guarantees via cwd, but a bare script path
    does not.
    """
    script_path = config.TOOLS_ROOT / script_name
    if not script_path.is_file():
        raise ToolExecutionError(f"unknown tool script: {script_name}")

    module_name = f"tools.{script_path.stem}"
    argv = [config.BOT_PYTHON_EXECUTABLE, "-m", module_name, "--json", *(extra_args or [])]

    try:
        result = subprocess.run(
            argv,
            cwd=config.PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=config.SUBPROCESS_TIMEOUT_SECONDS,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolExecutionError(f"{script_name} timed out") from exc

    if result.returncode != 0:
        raise ToolExecutionError(
            f"{script_name} exited {result.returncode}: {result.stderr[-2000:]}"
        )

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ToolExecutionError(f"{script_name} did not return valid JSON") from exc
