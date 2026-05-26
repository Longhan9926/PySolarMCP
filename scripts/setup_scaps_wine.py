#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from solarcell_sim.config import load_backend_options


def _command_with_xvfb(command: list[str], use_xvfb: bool) -> list[str]:
    if use_xvfb:
        return ["xvfb-run", "-a", *command]
    return command


def _run(command: list[str], env: dict[str, str], timeout_seconds: int) -> None:
    print("$ " + " ".join(command))
    subprocess.run(command, env=env, check=True, timeout=timeout_seconds)


def _find_bundled_msi(installer: Path) -> Path | None:
    if installer.suffix.lower() == ".msi":
        return installer

    preferred_dir = installer.parent / "bin" / "dp"
    candidates = sorted(preferred_dir.glob("*.msi"))
    if candidates:
        return candidates[0]

    candidates = sorted(installer.parent.glob("**/*.msi"))
    if candidates:
        return candidates[0]
    return None


def _installer_command(wine_bin: str, installer: Path) -> list[str]:
    msi = _find_bundled_msi(installer)
    if msi is not None:
        if msi != installer:
            print(f"Using bundled MSI installer: {msi}")
        return [wine_bin, "msiexec", "/i", str(msi), "/qn", "/norestart"]
    return [wine_bin, str(installer)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Initialize the SCAPS Wine prefix and optionally run the SCAPS installer."
    )
    parser.add_argument("--cwd", type=Path, default=REPO_ROOT, help="Directory containing .env.")
    parser.add_argument("--installer", type=Path, help="Path to the SCAPS setup.exe or bundled .msi installer.")
    parser.add_argument("--wine-bin", help="Override wine binary from .env.")
    parser.add_argument("--wineprefix", type=Path, help="Override WINEPREFIX from .env.")
    parser.add_argument("--winearch", default=None, help="Override WINEARCH. Defaults to .env or win32.")
    parser.add_argument("--no-xvfb", action="store_true", help="Do not wrap Wine commands with xvfb-run.")
    parser.add_argument("--timeout-seconds", type=int, default=300, help="Timeout for each Wine command.")
    args = parser.parse_args(argv)

    cwd = args.cwd.resolve()
    options = load_backend_options("scaps", cwd=cwd)
    wine_bin = args.wine_bin or options.wine_bin
    wine_prefix = (args.wineprefix or options.wine_prefix or (cwd / "wineprefix")).resolve()
    wine_arch = args.winearch or options.wine_arch or "win32"
    use_xvfb = bool(options.use_xvfb) and not args.no_xvfb

    if wine_prefix.exists() and any(wine_prefix.iterdir()):
        print(f"Using existing Wine prefix: {wine_prefix}")
        print("If this prefix was created as win64, WINEARCH=win32 will not convert it; create a fresh prefix instead.")
    else:
        wine_prefix.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["WINEPREFIX"] = str(wine_prefix)
    env["WINEARCH"] = wine_arch

    print(f"WINEPREFIX={wine_prefix}")
    print(f"WINEARCH={wine_arch}")
    _run(_command_with_xvfb([wine_bin, "wineboot", "-u"], use_xvfb), env, args.timeout_seconds)

    if args.installer:
        installer = args.installer.resolve()
        if not installer.exists():
            print(f"installer not found: {installer}", file=sys.stderr)
            return 2
        _run(_command_with_xvfb(_installer_command(wine_bin, installer), use_xvfb), env, args.timeout_seconds)

    print("Wine prefix setup completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
