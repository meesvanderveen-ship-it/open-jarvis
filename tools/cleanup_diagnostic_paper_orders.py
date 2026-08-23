#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def load_json_state(path: Path, root_key: str) -> Dict[str, Any]:
    if not path.exists():
        return {root_key: {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"Kon {path} niet als JSON lezen: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"Ongeldige state-structuur in {path}: root is {type(data).__name__}, verwacht dict")
    data.setdefault(root_key, {})
    return data


def is_diagnostic_record(record: Dict[str, Any]) -> bool:
    if not isinstance(record, dict):
        return False
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    risk = record.get("risk_check_result") if isinstance(record.get("risk_check_result"), dict) else {}
    fields = (
        record.get("client_order_id"),
        record.get("order_id"),
        record.get("intent_id"),
        record.get("ticker"),
        record.get("reason"),
        record.get("source"),
        record.get("source_kind"),
    )
    text = " ".join(str(x or "") for x in fields)
    return (
        "paper-diagnostic" in text
        or "diagnostic-" in text
        or "TEST-" in text
        or "TEST_" in text
        or "phase_b_diagnostic_" in text
        or "phase_b3_diagnostic_" in text
        or "phase_b4_diagnostic_" in text
        or "phase_b5_diagnostic_" in text
        or "phase_b6_diagnostic_" in text
        or metadata.get("diagnostic") is True
        or metadata.get("exclude_from_learning") is True
        or risk.get("diagnostic") is True
    )


# Backward-compatible names used by earlier tools/tests.
is_diagnostic_order = is_diagnostic_record


def iter_records(items_obj: Any) -> Iterable[Tuple[str, Dict[str, Any]]]:
    if isinstance(items_obj, dict):
        for key, item in items_obj.items():
            if isinstance(item, dict):
                yield str(key), item
    elif isinstance(items_obj, list):
        for idx, item in enumerate(items_obj):
            if isinstance(item, dict):
                key = str(item.get("client_order_id") or item.get("order_id") or item.get("intent_id") or idx)
                yield key, item


iter_orders = iter_records


def cleanup_state(data: Dict[str, Any], root_key: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]], int]:
    items_obj = data.get(root_key, {})
    removed: List[Dict[str, Any]] = []

    if isinstance(items_obj, dict):
        before = len(items_obj)
        kept: Dict[str, Dict[str, Any]] = {}
        for key, item in iter_records(items_obj):
            if is_diagnostic_record(item):
                removed.append(item)
            else:
                kept[key] = item
        new_data = dict(data)
        new_data[root_key] = kept
    elif isinstance(items_obj, list):
        before = len(items_obj)
        kept_list: List[Dict[str, Any]] = []
        for _key, item in iter_records(items_obj):
            if is_diagnostic_record(item):
                removed.append(item)
            else:
                kept_list.append(item)
        new_data = dict(data)
        new_data[root_key] = kept_list
    else:
        raise SystemExit(f"Ongeldige {root_key}-structuur: {type(items_obj).__name__}, verwacht dict of list")

    new_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    new_data["last_diagnostic_cleanup"] = {
        "generated_at": new_data["updated_at"],
        "root_key": root_key,
        "removed_count": len(removed),
        "dry_run_capable": True,
    }
    return new_data, removed, before


def cleanup_one_file(path: Path, root_key: str, backup_dir: Path, confirm: bool) -> Dict[str, Any]:
    data = load_json_state(path, root_key)
    new_data, removed, before = cleanup_state(data, root_key)
    after = before - len(removed)

    backup_path = None
    if confirm:
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{path.stem}.before_diagnostic_cleanup_{now_stamp()}.json"
        backup_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(new_data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return {
        "path": str(path),
        "root_key": root_key,
        "orders_before" if root_key == "orders" else "records_before": before,
        "diagnostic_orders_matched" if root_key == "orders" else "diagnostic_records_matched": len(removed),
        "orders_after" if root_key == "orders" else "records_after": after,
        "backup_path": str(backup_path) if backup_path else None,
        "removed": [
            {
                "client_order_id": item.get("client_order_id") or item.get("order_id") or item.get("intent_id"),
                "ticker": item.get("ticker"),
                "status": item.get("status"),
                "reason": item.get("reason"),
                "source_kind": item.get("source_kind"),
            }
            for item in removed
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verwijder diagnostic/test paper-orders en optioneel pending intents.")
    parser.add_argument("--path", default="state/open_orders.json", help="Pad naar open_orders.json")
    parser.add_argument("--backup-dir", default="state", help="Map waar backups worden geschreven bij --confirm-delete")
    parser.add_argument("--pending-intents-path", default="state/pending_order_intents.json", help="Pad naar pending_order_intents.json")
    parser.add_argument("--include-pending-intents", action="store_true", help="Ruim ook diagnostic pending intents op")
    parser.add_argument("--confirm-delete", action="store_true", help="Schrijf de cleanup echt weg. Zonder deze vlag is het dry-run.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    backup_dir = Path(args.backup_dir)
    order_result = cleanup_one_file(Path(args.path), "orders", backup_dir, args.confirm_delete)
    results: Dict[str, Any] = {
        "mode": "delete_confirmed" if args.confirm_delete else "dry_run_no_changes_written",
        "open_orders": order_result,
    }
    if args.include_pending_intents:
        results["pending_order_intents"] = cleanup_one_file(Path(args.pending_intents_path), "intents", backup_dir, args.confirm_delete)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    print("Phase-B diagnostic paper-order cleanup")
    print(f"mode: {results['mode']}")
    print(f"path: {order_result['path']}")
    print(f"orders_before: {order_result['orders_before']}")
    print(f"diagnostic_orders_matched: {order_result['diagnostic_orders_matched']}")
    print(f"orders_after: {order_result['orders_after']}")
    if order_result.get("backup_path"):
        print(f"backup_path: {order_result['backup_path']}")
    if order_result["removed"]:
        print("matched:")
        for item in order_result["removed"]:
            print(f"- {item['client_order_id']} | {item['ticker']} | {item['status']} | {item['reason']}")

    if args.include_pending_intents:
        pi = results["pending_order_intents"]
        print("\nPending order-intents")
        print(f"path: {pi['path']}")
        print(f"records_before: {pi['records_before']}")
        print(f"diagnostic_records_matched: {pi['diagnostic_records_matched']}")
        print(f"records_after: {pi['records_after']}")
        if pi.get("backup_path"):
            print(f"backup_path: {pi['backup_path']}")

    if not args.confirm_delete:
        print("Dry-run: niets verwijderd. Gebruik --confirm-delete om echt op te ruimen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
