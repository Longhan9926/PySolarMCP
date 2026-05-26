from __future__ import annotations

from solarcell_sim.schema import Diagnostic, SimulationMetrics


def result_quality_diagnostics(metrics: SimulationMetrics | None) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if metrics is None:
        return [
            Diagnostic(severity="error", code="result.metrics_missing", message="No SCAPS summary metrics were parsed")
        ]

    if metrics.extrapolated:
        diagnostics.append(
            Diagnostic(severity="warning", code="result.extrapolated", message="One or more SCAPS summary metrics are extrapolated")
        )
    if metrics.pce_percent is not None and metrics.pce_percent > 35:
        diagnostics.append(
            Diagnostic(severity="warning", code="result.pce_unusually_high", message="PCE is unusually high; verify input parameters and convergence")
        )
    if metrics.voc_v is not None and metrics.voc_v < 0:
        diagnostics.append(
            Diagnostic(severity="warning", code="result.negative_voc", message="Voc is negative")
        )
    return diagnostics

