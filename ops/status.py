from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from _common import configure_environment, last_run_path, output_dir, read_json


def main(argv: list[str] | None = None) -> int:
    configure_environment()

    parser = argparse.ArgumentParser(description="Show the latest local briefing run status.")
    parser.add_argument("--json", action="store_true", help="Print the status record as JSON.")
    args = parser.parse_args(argv)

    path = last_run_path()
    if not path.exists():
        message = f"No local daily run record found at {path}"
        if args.json:
            print(json.dumps({"ok": False, "attention": [message], "status_file": str(path)}))
        else:
            print(message)
        return 2

    record = read_json(path)
    derived = _derive_status(record)
    if args.json:
        print(json.dumps({**record, "derived": derived}, indent=2, sort_keys=True))
    else:
        _print_human(record, derived, path)
    return 0 if derived["ok"] else 2


def _derive_status(record: dict) -> dict:
    run = record.get("run") or {}
    delivery = record.get("delivery") or {}
    attention: list[str] = []

    run_date = run.get("run_date")
    today = _local_today()
    if _is_weekday(today) and run_date != today.isoformat():
        attention.append(f"no run recorded for today ({today.isoformat()})")

    run_status = run.get("status")
    if run_status != "succeeded":
        attention.append(f"latest run status is {run_status or 'missing'}")

    if record.get("error"):
        attention.append("latest local job recorded an error")
    if not record.get("ok"):
        attention.append("latest local job did not complete cleanly")

    manifest_path = Path(delivery.get("manifest_path") or output_dir() / "published/latest/manifest.json")
    manifest_ok = None
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_ok = manifest.get("run_id") == run.get("run_id")
            if not manifest_ok:
                attention.append("published latest manifest does not match the latest run id")
        except json.JSONDecodeError:
            manifest_ok = False
            attention.append("published latest manifest is not valid JSON")
    elif delivery:
        manifest_ok = False
        attention.append(f"published latest manifest is missing at {manifest_path}")

    ok = bool(record.get("ok")) and not attention
    return {
        "ok": ok,
        "today": today.isoformat(),
        "attention": attention,
        "manifest_ok": manifest_ok,
        "manifest_path": str(manifest_path),
    }


def _print_human(record: dict, derived: dict, status_path: Path) -> None:
    run = record.get("run") or {}
    delivery = record.get("delivery") or {}
    print("Last local daily run")
    print(f"  Status file: {status_path}")
    print(f"  Finished: {record.get('finished_at') or 'unknown'}")
    print(f"  Run: {run.get('run_id') or 'none'}")
    print(f"  Run date: {run.get('run_date') or 'none'}")
    print(f"  Run status: {run.get('status') or 'missing'}")
    print(f"  Data mode: {run.get('data_mode') or 'unknown'}")
    print(f"  Published latest: {delivery.get('latest_html_path') or 'not published'}")
    print(f"  Manifest: {derived.get('manifest_path')}")
    if derived["attention"]:
        print("  Attention:")
        for item in derived["attention"]:
            print(f"    - {item}")
    else:
        print("  Attention: none")


def _local_today() -> date:
    timezone = os.getenv("GENERIC_TIMEZONE") or "Europe/Lisbon"
    try:
        return datetime.now(ZoneInfo(timezone)).date()
    except ZoneInfoNotFoundError:
        return date.today()


def _is_weekday(day: date) -> bool:
    return day.weekday() < 5


if __name__ == "__main__":
    raise SystemExit(main())
