from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from solarcell_sim.schema import BackendOptions, Diagnostic, PreparedCase, RawRunResult


def posix_to_wine_path(path: Path) -> str:
    resolved = path.resolve()
    return "Z:" + str(resolved).replace("/", "\\")


def _copy_path(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst)
        return
    shutil.copy2(src, dst)


def _link_or_copy(src: Path, dst: Path, copy: bool) -> None:
    if dst.exists() or dst.is_symlink():
        return
    if copy:
        _copy_path(src, dst)
        return
    try:
        dst.symlink_to(src, target_is_directory=src.is_dir())
    except OSError:
        _copy_path(src, dst)


SCAPS_ERROR_LOG_NAME = "SCAPSErrorLogFile.log"


def _log_snippet(path: Path, limit: int = 600) -> str:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _find_scaps_error_log(prepared: PreparedCase) -> Path | None:
    candidates = [
        prepared.scaps_root / SCAPS_ERROR_LOG_NAME,
        prepared.scaps_root / "script" / SCAPS_ERROR_LOG_NAME,
        prepared.scaps_root / "results" / SCAPS_ERROR_LOG_NAME,
    ]
    candidates.extend(sorted(prepared.scaps_root.glob(f"**/{SCAPS_ERROR_LOG_NAME}")))
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
        except OSError:
            continue
    return None


class SubprocessScapsRunner:
    name = "subprocess"

    def materialize_runtime(self, prepared: PreparedCase, config: BackendOptions) -> Path:
        if config.executable_path is None:
            raise FileNotFoundError("SCAPS executable path is not configured")
        executable = config.executable_path
        if not executable.exists():
            raise FileNotFoundError(f"SCAPS executable does not exist: {executable}")

        if config.runtime_strategy == "in_place":
            return executable

        prepared.scaps_root.mkdir(parents=True, exist_ok=True)
        if executable.parent.resolve() == prepared.scaps_root.resolve():
            return executable

        copy_files = config.runtime_strategy == "workspace_copy"
        for source in executable.parent.iterdir():
            _link_or_copy(source, prepared.scaps_root / source.name, copy=copy_files)
        return prepared.scaps_root / executable.name

    def run_command(self, command: list[str], prepared: PreparedCase, config: BackendOptions) -> RawRunResult:
        env = os.environ.copy()
        if config.wine_prefix is not None:
            env["WINEPREFIX"] = str(config.wine_prefix)
        if config.wine_arch:
            env["WINEARCH"] = config.wine_arch

        try:
            completed = subprocess.run(
                command,
                cwd=prepared.scaps_root,
                env=env,
                capture_output=True,
                text=True,
                timeout=config.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return RawRunResult(
                run_id=prepared.run_id,
                status="failed",
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                diagnostics=[
                    Diagnostic(
                        severity="error",
                        code="runner.timeout",
                        message=f"SCAPS execution timed out after {config.timeout_seconds} seconds",
                    )
                ],
            )
        except OSError as exc:
            return RawRunResult(
                run_id=prepared.run_id,
                status="failed",
                diagnostics=[
                    Diagnostic(severity="error", code="runner.os_error", message=str(exc))
                ],
            )

        result_file = prepared.result_file if prepared.result_file.exists() else None
        error_log_file = _find_scaps_error_log(prepared)
        if result_file is not None:
            status = "success" if completed.returncode == 0 and error_log_file is None else "partial"
        else:
            status = "failed"
        diagnostics: list[Diagnostic] = []
        if completed.returncode != 0:
            diagnostics.append(
                Diagnostic(
                    severity="warning" if result_file is not None else "error",
                    code="runner.nonzero_exit",
                    message=(
                        f"SCAPS exited with code {completed.returncode}"
                        if result_file is None
                        else (
                            f"SCAPS exited with code {completed.returncode} after creating output; "
                            "the SCAPS manual does not define this process code, so the output is returned"
                        )
                    ),
                )
            )
        if error_log_file is not None:
            diagnostics.append(
                Diagnostic(
                    severity="warning" if result_file is not None else "error",
                    code="scaps.error_log",
                    message=f"SCAPS wrote {error_log_file.name}: {_log_snippet(error_log_file)}",
                )
            )
        if result_file is None:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="runner.output_missing",
                    message=f"Expected SCAPS output was not created: {prepared.result_file}",
                )
            )

        return RawRunResult(
            run_id=prepared.run_id,
            status=status,
            stdout=completed.stdout,
            stderr=completed.stderr,
            return_code=completed.returncode,
            result_file=result_file,
            error_log_file=error_log_file,
            diagnostics=diagnostics,
        )

