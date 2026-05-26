from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from solarcell_sim.schema import BackendOptions, Diagnostic, PreparedCase, RawRunResult


def posix_to_wine_path(path: Path) -> str:
    resolved = path.resolve()
    return "Z:" + str(resolved).replace("/", "\\")


def _link_or_copy(src: Path, dst: Path, copy: bool) -> None:
    if dst.exists() or dst.is_symlink():
        return
    if copy:
        shutil.copy2(src, dst)
        return
    try:
        dst.symlink_to(src)
    except OSError:
        shutil.copy2(src, dst)


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
        copy_files = config.runtime_strategy == "workspace_copy"
        runtime_executable = prepared.scaps_root / executable.name
        _link_or_copy(executable, runtime_executable, copy=copy_files)
        return runtime_executable

    def run_command(self, command: list[str], prepared: PreparedCase, config: BackendOptions) -> RawRunResult:
        env = os.environ.copy()
        if config.wine_prefix is not None:
            env["WINEPREFIX"] = str(config.wine_prefix)

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
        status = "success" if completed.returncode == 0 and result_file else "failed"
        diagnostics: list[Diagnostic] = []
        if completed.returncode != 0:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="runner.nonzero_exit",
                    message=f"SCAPS exited with code {completed.returncode}",
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
            diagnostics=diagnostics,
        )

