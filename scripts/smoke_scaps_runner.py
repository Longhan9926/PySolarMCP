#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pydantic import ValidationError

from solarcell_sim.api import check_backend
from solarcell_sim.backends.registry import get_backend
from solarcell_sim.config import load_backend_options
from solarcell_sim.schema import Diagnostic, SimulationInput


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _print_header(title: str) -> None:
    print(f"\n== {title} ==")


def _print_diagnostics(diagnostics: list[Diagnostic]) -> None:
    if not diagnostics:
        print("diagnostics: none")
        return
    print("diagnostics:")
    for item in diagnostics:
        print(f"  - [{item.severity}] {item.code}: {item.message}")


def _print_text_block(label: str, value: str, limit: int) -> None:
    if not value:
        print(f"{label}: <empty>")
        return
    text = value if len(value) <= limit else value[-limit:]
    suffix = "" if len(value) <= limit else f"\n... trimmed to last {limit} chars"
    print(f"{label}:{suffix}\n{text}")


def _case_for_run(args: argparse.Namespace) -> dict[str, Any]:
    case = _load_json(args.case)
    if not args.use_case_backend_options:
        case.pop("backendOptions", None)

    overrides: dict[str, Any] = {}
    if args.runner:
        overrides["runner"] = args.runner
    if args.timeout_seconds:
        overrides["timeoutSeconds"] = args.timeout_seconds
    if args.runtime_strategy:
        overrides["runtimeStrategy"] = args.runtime_strategy
    if args.executable_path:
        overrides["executablePath"] = str(args.executable_path)
    if args.definition_path:
        overrides["definitionSource"] = {"type": "baseline_file", "path": str(args.definition_path)}
    if args.workdir:
        overrides["workdir"] = str(args.workdir)

    if overrides:
        case.setdefault("backendOptions", {}).update(overrides)
    return case


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test the SCAPS runner using the project .env and a sample case."
    )
    parser.add_argument(
        "--case",
        type=Path,
        default=REPO_ROOT / "examples" / "nip_baseline.json",
        help="Simulation case JSON to run. Defaults to examples/nip_baseline.json.",
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=REPO_ROOT,
        help="Project/config directory. The script reads .env from this directory.",
    )
    parser.add_argument(
        "--use-case-backend-options",
        action="store_true",
        help="Keep backendOptions from the case file instead of using .env/project config.",
    )
    parser.add_argument("--prepare-only", action="store_true", help="Prepare inputs but do not invoke SCAPS.")
    parser.add_argument("--force-run", action="store_true", help="Run even if check_backend reports unavailable.")
    parser.add_argument("--runner", choices=["wine", "direct", "windows_native"], help="Override runner.")
    parser.add_argument("--runtime-strategy", choices=["workspace_link", "workspace_copy", "in_place"], help="Override runtime strategy.")
    parser.add_argument("--timeout-seconds", type=int, help="Override SCAPS runner timeout.")
    parser.add_argument("--executable-path", type=Path, help="Override SCAPS executable path.")
    parser.add_argument("--definition-path", type=Path, help="Override baseline .scaps path.")
    parser.add_argument("--workdir", type=Path, help="Override run workdir.")
    parser.add_argument("--log-chars", type=int, default=4000, help="Max stdout/stderr chars to print from each stream.")
    args = parser.parse_args(argv)

    args.cwd = args.cwd.resolve()
    args.case = args.case.resolve()
    if args.executable_path:
        args.executable_path = args.executable_path.resolve()
    if args.definition_path:
        args.definition_path = args.definition_path.resolve()
    if args.workdir:
        args.workdir = args.workdir.resolve()

    os.chdir(args.cwd)

    _print_header("Input")
    print(f"cwd: {args.cwd}")
    print(f"case: {args.case}")
    print(f"dotenv: {args.cwd / '.env'}")

    try:
        case = _case_for_run(args)
        parsed = SimulationInput.model_validate(case)
        options = load_backend_options(parsed.backend, parsed.backend_options, cwd=args.cwd)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"failed to load case/config: {exc}", file=sys.stderr)
        return 2

    _print_header("Resolved Backend Options")
    print(f"backend: {parsed.backend}")
    print(f"runner: {options.runner}")
    print(f"executable_path: {options.executable_path}")
    print(f"definition_path: {options.definition_source.path if options.definition_source else None}")
    print(f"workdir: {options.workdir}")
    print(f"runtime_strategy: {options.runtime_strategy}")
    print(f"wine_bin: {options.wine_bin}")
    print(f"wine_prefix: {options.wine_prefix}")
    print(f"use_xvfb: {options.use_xvfb}")
    print(f"timeout_seconds: {options.timeout_seconds}")

    _print_header("Backend Check")
    status = check_backend(parsed.backend, backend_options=parsed.backend_options, cwd=args.cwd)
    print(f"status: {status.status}")
    print(f"runner: {status.runner}")
    print(f"executable_path: {status.executable_path}")
    print(f"definition_path: {status.definition_path}")
    print(f"workdir: {status.workdir}")
    print(f"wine_bin: {status.wine_bin}")
    print(f"wine_prefix: {status.wine_prefix}")
    _print_diagnostics(status.diagnostics)
    if status.status != "available" and not args.force_run:
        print("\nBackend is not available. Fix the diagnostics above or rerun with --force-run.")
        return 3

    backend = get_backend(parsed.backend)

    _print_header("Prepare Case")
    try:
        prepared = backend.prepare_case(parsed, options)
    except Exception as exc:  # noqa: BLE001 - smoke script should surface unexpected runner setup failures.
        print(f"prepare failed: {exc}", file=sys.stderr)
        return 4
    print(f"run_id: {prepared.run_id}")
    print(f"workdir: {prepared.workdir}")
    print(f"scaps_root: {prepared.scaps_root}")
    print(f"definition: {prepared.definition.path}")
    print(f"script: {prepared.script.path}")
    print(f"expected_result_file: {prepared.result_file}")
    _print_diagnostics(prepared.diagnostics)

    if args.prepare_only:
        print("\nprepare-only mode: runner was not invoked.")
        return 0

    _print_header("Run SCAPS")
    try:
        raw = backend.run_case(prepared, options)
    except Exception as exc:  # noqa: BLE001
        print(f"runner raised an exception: {exc}", file=sys.stderr)
        return 5
    print(f"raw_status: {raw.status}")
    print(f"return_code: {raw.return_code}")
    print(f"result_file: {raw.result_file}")
    _print_diagnostics(raw.diagnostics)
    _print_text_block("stdout", raw.stdout, args.log_chars)
    _print_text_block("stderr", raw.stderr, args.log_chars)

    _print_header("Parse Result")
    result = backend.parse_results(raw, prepared)
    print(f"result_status: {result.status}")
    print(f"run_id: {result.run_id}")
    if result.metrics:
        print("metrics:")
        for key, value in result.metrics.model_dump(mode="json").items():
            print(f"  {key}: {value}")
    else:
        print("metrics: none")
    _print_diagnostics(result.diagnostics)
    if result.artifacts:
        print("artifacts:")
        for artifact in result.artifacts:
            print(f"  - {artifact.type}: {artifact.path}")

    return 0 if result.status == "success" else 6


if __name__ == "__main__":
    raise SystemExit(main())
