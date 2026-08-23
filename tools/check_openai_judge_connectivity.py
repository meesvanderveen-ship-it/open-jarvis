#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
from typing import Any, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import BotConfig  # noqa: E402
from bot.llm_clients import _provider_error_type  # noqa: E402
from bot.phase_d6_report_bundle_writer import assert_reports_d6_output_path  # noqa: E402


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, data: bytes) -> None:
    safe = assert_reports_d6_output_path(path)
    safe.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = safe.with_name(f".{safe.name}.tmp")
    tmp_path.write_bytes(data)
    os.replace(tmp_path, safe)


def _dns(host: str) -> dict[str, Any]:
    try:
        return {"host": host, "ok": True, "address": socket.gethostbyname(host), "error": ""}
    except Exception as exc:
        return {"host": host, "ok": False, "address": "", "error": repr(exc)}


def build_report(*, timeout: float = 10.0, probe_models_endpoint: bool = True) -> dict[str, Any]:
    cfg_status: dict[str, Any]
    try:
        cfg = BotConfig()
        cfg.validate()
        cfg_status = {
            "ok": True,
            "openai_api_key_present": bool(getattr(cfg, "openai_api_key", "")),
            "openai_model": getattr(cfg, "openai_model", ""),
            "openai_judge_model": getattr(cfg, "openai_judge_model", ""),
        }
        api_key = getattr(cfg, "openai_api_key", "")
    except Exception as exc:
        cfg_status = {
            "ok": False,
            "openai_api_key_present": False,
            "openai_model": "",
            "openai_judge_model": "",
            "error": str(exc),
        }
        api_key = ""

    dns_results = [_dns("api.openai.com"), _dns("chatgpt.com")]
    http_probe: dict[str, Any] = {"attempted": False}
    if probe_models_endpoint:
        http_probe["attempted"] = True
        try:
            import httpx

            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            response = httpx.get("https://api.openai.com/v1/models", headers=headers, timeout=timeout)
            http_probe.update(
                {
                    "ok": 200 <= response.status_code < 300,
                    "status_code": response.status_code,
                    "body_prefix": response.text[:160],
                }
            )
        except Exception as exc:
            http_probe.update(
                {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": repr(exc),
                    "provider_error_type": _provider_error_type(exc),
                }
            )

    blockers: list[str] = []
    if not cfg_status.get("ok"):
        blockers.append("bot_config_invalid")
    if not cfg_status.get("openai_api_key_present"):
        blockers.append("openai_api_key_missing")
    if not all(row.get("ok") for row in dns_results):
        blockers.append("openai_dns_resolution_failed")
    if http_probe.get("attempted") and not http_probe.get("ok"):
        blockers.append(http_probe.get("provider_error_type") or "openai_http_probe_failed")

    return {
        "generated_at": _now_iso(),
        "report_type": "openai_judge_connectivity_check",
        "no_submit": True,
        "coinbase_write_attempted": False,
        "state_write_performed": False,
        "env_mutation_performed": False,
        "bot_start_attempted": False,
        "python": sys.executable,
        "openai_spec_present": importlib.util.find_spec("openai") is not None,
        "httpx_spec_present": importlib.util.find_spec("httpx") is not None,
        "process_env": {
            "OPENAI_API_KEY_present": bool(os.getenv("OPENAI_API_KEY")),
            "OPENAI_MODEL": os.getenv("OPENAI_MODEL", ""),
            "OPENAI_JUDGE_MODEL": os.getenv("OPENAI_JUDGE_MODEL", ""),
            "HTTPS_PROXY_present": bool(os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")),
            "HTTP_PROXY_present": bool(os.getenv("HTTP_PROXY") or os.getenv("http_proxy")),
        },
        "bot_config": cfg_status,
        "dns": dns_results,
        "http_probe": http_probe,
        "status": "ok" if not blockers else "blocked",
        "blockers": sorted(set(blockers)),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# OpenAI Judge Connectivity Check",
        "",
        "No-submit diagnostic. It does not call Coinbase, write trading state, mutate `.env`, or start the bot.",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- status: `{report.get('status')}`",
        f"- blockers: `{report.get('blockers')}`",
        f"- python: `{report.get('python')}`",
        f"- openai_spec_present: `{report.get('openai_spec_present')}`",
        f"- httpx_spec_present: `{report.get('httpx_spec_present')}`",
        f"- cfg_openai_key_present: `{(report.get('bot_config') or {}).get('openai_api_key_present')}`",
        f"- cfg_openai_model: `{(report.get('bot_config') or {}).get('openai_model')}`",
        f"- cfg_openai_judge_model: `{(report.get('bot_config') or {}).get('openai_judge_model')}`",
        "",
        "## DNS",
        "",
        "```json",
        json.dumps(report.get("dns") or [], indent=2, sort_keys=True),
        "```",
        "",
        "## HTTP Probe",
        "",
        "```json",
        json.dumps(report.get("http_probe") or {}, indent=2, sort_keys=True),
        "```",
        "",
    ]
    return "\n".join(lines) + "\n"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="No-submit OpenAI judge connectivity diagnostic.")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--no-http-probe", action="store_true")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--markdown-out", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_report(timeout=args.timeout, probe_models_endpoint=not args.no_http_probe)
    json_text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    markdown_text = render_markdown(report)
    if args.json_out:
        _atomic_write(Path(args.json_out), json_text.encode("utf-8"))
    if args.markdown_out:
        _atomic_write(Path(args.markdown_out), markdown_text.encode("utf-8"))
    if args.json:
        print(json_text, end="")
    else:
        print(
            "openai_judge_connectivity "
            f"status={report.get('status')} "
            f"blockers={report.get('blockers')} "
            f"cfg_key_present={(report.get('bot_config') or {}).get('openai_api_key_present')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
