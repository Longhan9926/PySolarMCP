from __future__ import annotations

import os
import shutil
import subprocess
import sys

from solarcell_sim.runners.base import SubprocessScapsRunner, posix_to_wine_path
from solarcell_sim.schema import BackendOptions, Diagnostic, PreparedCase, RawRunResult

XVFB_SERVER_ARGS = "-screen 0 1280x1024x24"


class WineScapsRunner(SubprocessScapsRunner):
    name = "wine"

    def check_runner(self, config: BackendOptions) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        if shutil.which(config.wine_bin) is None:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="runner.wine_missing",
                    message=f"Wine binary was not found: {config.wine_bin}",
                )
            )
        if config.use_xvfb and shutil.which(config.xvfb_bin) is None:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="runner.xvfb_missing",
                    message=f"Xvfb wrapper was not found: {config.xvfb_bin}",
                )
            )
        elif config.use_xvfb:
            diagnostics.extend(self._check_xvfb_starts(config))
        elif not os.environ.get("DISPLAY"):
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="runner.display_unavailable",
                    message="Wine runner is not using Xvfb and DISPLAY is not set; enable SOLARCELL_SIM_XVFB=1.",
                )
            )
        return diagnostics

    def _check_xvfb_starts(self, config: BackendOptions) -> list[Diagnostic]:
        command = [
            config.xvfb_bin,
            "-a",
            f"--server-args={XVFB_SERVER_ARGS}",
            sys.executable,
            "-c",
            "import os, sys; sys.exit(0 if os.environ.get('DISPLAY') else 1)",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=8,
            )
        except subprocess.TimeoutExpired:
            return [
                Diagnostic(
                    severity="error",
                    code="runner.display_unavailable",
                    message="Xvfb preflight timed out; Wine/SCAPS cannot be started reliably.",
                )
            ]
        except OSError as exc:
            return [
                Diagnostic(
                    severity="error",
                    code="runner.display_unavailable",
                    message=f"Xvfb preflight failed to start: {exc}",
                )
            ]

        if completed.returncode == 0:
            return []
        output = " ".join(f"{completed.stdout or ''} {completed.stderr or ''}".split())
        return [
            Diagnostic(
                severity="error",
                code="runner.display_unavailable",
                message=f"Xvfb preflight failed with exit code {completed.returncode}: {output}",
            )
        ]

    def run(self, prepared: PreparedCase, config: BackendOptions) -> RawRunResult:
        runtime_executable = self.materialize_runtime(prepared, config)
        command = [config.wine_bin, posix_to_wine_path(runtime_executable), prepared.script.path.name]
        if config.use_xvfb:
            command = [config.xvfb_bin, "-a", f"--server-args={XVFB_SERVER_ARGS}", *command]
        return self.run_command(command, prepared, config)


class DirectScapsRunner(SubprocessScapsRunner):
    name = "direct"

    def check_runner(self, config: BackendOptions) -> list[Diagnostic]:
        return []

    def run(self, prepared: PreparedCase, config: BackendOptions) -> RawRunResult:
        runtime_executable = self.materialize_runtime(prepared, config)
        return self.run_command([str(runtime_executable), prepared.script.path.name], prepared, config)
