from __future__ import annotations

import os

from solarcell_sim.runners.wine import DirectScapsRunner
from solarcell_sim.schema import BackendOptions, Diagnostic


class NativeWindowsScapsRunner(DirectScapsRunner):
    name = "windows_native"

    def check_runner(self, config: BackendOptions) -> list[Diagnostic]:
        if os.name != "nt":
            return [
                Diagnostic(
                    severity="error",
                    code="runner.windows_required",
                    message="windows_native runner requires a Windows Python environment",
                )
            ]
        return []

