from __future__ import annotations

from solarcell_sim.schema import Diagnostic


class SolarCellSimError(Exception):
    def __init__(self, message: str, diagnostics: list[Diagnostic] | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics or [
            Diagnostic(severity="error", code="solarcell_sim.error", message=message)
        ]


class ConfigurationError(SolarCellSimError):
    pass


class ValidationError(SolarCellSimError):
    pass

