from __future__ import annotations

import argparse
from pathlib import Path
import plistlib
import subprocess

from _common import REPO_ROOT, configure_environment


LABEL = "com.fernando.briefing.daily"
PLIST_NAME = f"{LABEL}.plist"


def main(argv: list[str] | None = None) -> int:
    configure_environment()

    parser = argparse.ArgumentParser(description="Generate or install the local launchd job.")
    parser.add_argument(
        "--install",
        action="store_true",
        help="Write the plist to ~/Library/LaunchAgents instead of ops/launchd.",
    )
    parser.add_argument(
        "--load",
        action="store_true",
        help="Load the LaunchAgent after writing it. Implies --install.",
    )
    args = parser.parse_args(argv)

    target = _user_launch_agent_path() if args.install or args.load else _repo_plist_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if args.install or args.load:
        _ops_log_dir().mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        plistlib.dump(_plist(), handle, sort_keys=False)
    print(f"Wrote {target}")

    if args.load:
        _load(target)
    return 0


def _plist() -> dict:
    python = REPO_ROOT / ".venv/bin/python"
    run_script = REPO_ROOT / "ops/run_daily.py"
    ops_log_dir = _ops_log_dir()
    return {
        "Label": LABEL,
        "ProgramArguments": [str(python), str(run_script)],
        "WorkingDirectory": str(REPO_ROOT),
        "EnvironmentVariables": {
            "PYTHONPATH": str(REPO_ROOT / "src"),
        },
        "StartCalendarInterval": [
            {"Weekday": weekday, "Hour": 6, "Minute": 30}
            for weekday in range(1, 6)
        ],
        "StandardOutPath": str(ops_log_dir / "launchd.out.log"),
        "StandardErrorPath": str(ops_log_dir / "launchd.err.log"),
        "RunAtLoad": False,
    }


def _repo_plist_path() -> Path:
    return REPO_ROOT / "ops/launchd" / PLIST_NAME


def _ops_log_dir() -> Path:
    return REPO_ROOT / "data/ops"


def _user_launch_agent_path() -> Path:
    return Path.home() / "Library/LaunchAgents" / PLIST_NAME


def _load(path: Path) -> None:
    domain = f"gui/{subprocess.check_output(['id', '-u'], text=True).strip()}"
    subprocess.run(["launchctl", "bootout", domain, str(path)], check=False)
    subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
    subprocess.run(["launchctl", "enable", f"{domain}/{LABEL}"], check=True)
    print(f"Loaded {LABEL} in {domain}")


if __name__ == "__main__":
    raise SystemExit(main())
