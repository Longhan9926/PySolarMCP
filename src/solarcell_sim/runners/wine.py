from __future__ import annotations

import shutil

from solarcell_sim.runners.base import SubprocessScapsRunner, posix_to_wine_path
from solarcell_sim.schema import BackendOptions, Diagnostic, PreparedCase, RawRunResult


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
        return diagnostics

    def run(self, prepared: PreparedCase, config: BackendOptions) -> RawRunResult:
        runtime_executable = self.materialize_runtime(prepared, config)
        command = [config.wine_bin, posix_to_wine_path(runtime_executable), prepared.script.path.name]
        if config.use_xvfb:
            command = [config.xvfb_bin, "-a", *command]
        return self.run_command(command, prepared, config)


class DirectScapsRunner(SubprocessScapsRunner):
    name = "direct"

    def check_runner(self, config: BackendOptions) -> list[Diagnostic]:
        return []

    def run(self, prepared: PreparedCase, config: BackendOptions) -> RawRunResult:
        runtime_executable = self.materialize_runtime(prepared, config)
        return self.run_command([str(runtime_executable), prepared.script.path.name], prepared, config)

