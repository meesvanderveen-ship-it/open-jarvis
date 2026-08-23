#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from typing import Any, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_report_bundle_writer import assert_reports_d6_output_path  # noqa: E402


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run(args: list[str], *, timeout: float = 8.0) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            args,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return {
            "args": args,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
    except Exception as exc:
        return {"args": args, "returncode": None, "stdout": "", "stderr": repr(exc)}


def _read(path: str) -> dict[str, Any]:
    p = Path(path)
    try:
        return {"path": path, "ok": True, "text": p.read_text(encoding="utf-8", errors="replace")}
    except Exception as exc:
        return {"path": path, "ok": False, "text": "", "error": repr(exc)}


def _dns(host: str) -> dict[str, Any]:
    try:
        return {"host": host, "ok": True, "address": socket.gethostbyname(host), "error": ""}
    except Exception as exc:
        return {"host": host, "ok": False, "address": "", "error": repr(exc)}


def _state_hashes() -> dict[str, Any]:
    return _run(["sha256sum", "state/open_orders.json", "state/positions.json"])


def build_report(*, mode: str) -> dict[str, Any]:
    resolv_conf = _read("/etc/resolv.conf")
    upstream_resolv_conf = _read("/run/systemd/resolve/resolv.conf")
    stub_readlink = _run(["readlink", "-f", "/etc/resolv.conf"])
    return {
        "generated_at": _now_iso(),
        "report_type": "dns_runtime_mismatch_diagnostic",
        "mode": mode,
        "no_submit": True,
        "coinbase_write_attempted": False,
        "coinbase_cancel_replace_submit_attempted": False,
        "state_write_performed": False,
        "env_mutation_performed": False,
        "bot_start_or_restart_attempted": False,
        "trading_state_hashes": _state_hashes(),
        "runtime": {
            "cwd": str(Path.cwd()),
            "python": sys.executable,
            "user": os.getenv("USER", ""),
            "openai_api_key_present": bool(os.getenv("OPENAI_API_KEY")),
            "http_proxy_present": bool(os.getenv("HTTP_PROXY") or os.getenv("http_proxy")),
            "https_proxy_present": bool(os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")),
        },
        "host_context_observed_by_operator": {
            "summary": "User supplied prior host-shell evidence: api.openai.com DNS ok, chatgpt.com DNS ok, /v1/models HTTP 200, OPENAI_API_KEY_present=true, status=ok.",
            "resolv_conf": "nameserver 127.0.0.53, search netbird.cloud",
            "systemd_resolved": "active per user-provided host context",
            "route_to_1_1_1_1": "present per user-provided host context",
        },
        "codex_runtime_context": {
            "resolv_conf": resolv_conf,
            "upstream_resolv_conf": upstream_resolv_conf,
            "resolv_conf_target": stub_readlink,
            "ip_route_get_1_1_1_1": _run(["ip", "route", "get", "1.1.1.1"]),
            "resolvectl_status": _run(["resolvectl", "status"]),
            "resolvectl_query_api_openai": _run(["resolvectl", "query", "api.openai.com"]),
            "getent_api_openai": _run(["getent", "hosts", "api.openai.com"]),
            "getent_chatgpt": _run(["getent", "hosts", "chatgpt.com"]),
            "socket_dns": [
                _dns("api.openai.com"),
                _dns("chatgpt.com"),
                _dns("google.com"),
                _dns("cloudflare-dns.com"),
            ],
            "netbird_status": _run(["netbird", "status"], timeout=12.0),
        },
        "wrapper_difference": {
            "summary": "Wrapper loads .env and full-bot maker-buy safety environment. It made OPENAI_API_KEY present, but DNS failed identically.",
            "wrapper_sets_bot_config_skip_dotenv": True,
            "wrapper_changes_dns": False,
        },
        "exact_difference": [
            "User-provided normal host shell can resolve OpenAI and receive HTTP 200.",
            "Codex/runtime and wrapper path cannot use netlink, system bus, NetBird daemon socket, or systemd-resolved stub DNS at 127.0.0.53.",
            "Both getent/resolvectl and Python socket resolution fail in this runtime.",
            "/etc/resolv.conf points to /run/systemd/resolve/stub-resolv.conf; the direct upstream resolver file is visible at /run/systemd/resolve/resolv.conf.",
        ],
        "diagnosis": {
            "cause": "Sandbox/runtime namespace cannot access host systemd-resolved and related host control sockets even though the host shell can. This is a runtime isolation mismatch, not a missing OpenAI key and not a wrapper environment bug.",
            "netbird_influence": "NetBird may affect host DNS/search domains, but this runtime cannot inspect the daemon socket. Do not disable NetBird from this task.",
            "safe_repair_attempted": "resolvectl flush-caches was attempted and failed with sd_bus_open_system: Operation not permitted.",
            "fix_applied": False,
            "fix_blocked_reason": "Approval policy and filesystem sandbox prevent host DNS mutation; resolvectl/systemctl/netbird control paths are unavailable from this runtime.",
        },
        "proposed_fix": [
            "Run the live wrapper command path from the same host namespace where /etc/resolv.conf/systemd-resolved works, or launch Codex/wrapper with access to host DNS/system bus.",
            "Host-side safe repair: resolvectl flush-caches; if still failing and eth0 is the default route, resolvectl dns eth0 1.1.1.1 8.8.8.8; resolvectl domain eth0 '~.'; resolvectl flush-caches.",
            "If the sandbox must remain isolated, provide a resolv.conf inside that namespace that points directly at reachable upstream DNS rather than 127.0.0.53.",
            "Do not edit /etc/resolv.conf directly unless resolvectl methods fail and a rollback plan is accepted.",
        ],
        "readiness": {
            "openai_stable_ok_twice": False,
            "full_no_submit_chain_allowed_to_proceed": False,
            "actual_submit_allowed_now": False,
            "stop_reason": "openai_connectivity_not_stable_in_wrapper_runtime",
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    diagnosis = report["diagnosis"]
    readiness = report["readiness"]
    lines = [
        "# DNS Runtime Mismatch Diagnostic",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- mode: `{report['mode']}`",
        f"- cause: `{diagnosis['cause']}`",
        f"- fix_applied: `{diagnosis['fix_applied']}`",
        f"- fix_blocked_reason: `{diagnosis['fix_blocked_reason']}`",
        f"- openai_stable_ok_twice: `{readiness['openai_stable_ok_twice']}`",
        f"- full_no_submit_chain_allowed_to_proceed: `{readiness['full_no_submit_chain_allowed_to_proceed']}`",
        f"- actual_submit_allowed_now: `{readiness['actual_submit_allowed_now']}`",
        f"- stop_reason: `{readiness['stop_reason']}`",
        "",
        "## Exact Difference",
        "",
    ]
    lines.extend(f"- {item}" for item in report["exact_difference"])
    lines.extend(
        [
            "",
            "## Proposed Fix",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report["proposed_fix"])
    lines.extend(
        [
            "",
            "## No-Live-Action Confirmation",
            "",
            "- Coinbase write/order endpoints: `not attempted`",
            "- submit/cancel/replace: `not attempted`",
            "- trading state write: `false`",
            "- `.env` mutation: `false`",
            "- bot start/restart: `false`",
            "",
            "## Runtime Evidence",
            "",
            "```json",
            json.dumps(report["codex_runtime_context"], indent=2, sort_keys=True),
            "```",
            "",
            "## State Hashes",
            "",
            "```text",
            (report.get("trading_state_hashes") or {}).get("stdout", ""),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _atomic_write(path: Path, text: str) -> None:
    safe = assert_reports_d6_output_path(path)
    safe.parent.mkdir(parents=True, exist_ok=True)
    tmp = safe.with_name(f".{safe.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, safe)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build DNS runtime mismatch diagnostic reports.")
    parser.add_argument("--mode", default="diagnostic")
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--markdown-out", required=True)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_report(mode=args.mode)
    json_text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    markdown_text = render_markdown(report) + "\n"
    _atomic_write(Path(args.json_out), json_text)
    _atomic_write(Path(args.markdown_out), markdown_text)
    if args.json:
        print(json_text, end="")
    else:
        print(
            "dns_runtime_mismatch "
            f"mode={args.mode} "
            f"fix_applied={report['diagnosis']['fix_applied']} "
            f"stop_reason={report['readiness']['stop_reason']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
