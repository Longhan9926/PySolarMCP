from __future__ import annotations

from pathlib import Path
from typing import Protocol

from solarcell_sim.schema import (
    BackendOptions,
    BackendStatus,
    PreparedCase,
    RawRunResult,
    SimulationInput,
    SimulationResult,
    ValidationReport,
)


class SimulatorBackend(Protocol):
    name: str
    version: str | None

    def check_available(self, config: BackendOptions) -> BackendStatus: ...

    def validate_input(self, case: SimulationInput) -> ValidationReport: ...

    def prepare_case(self, case: SimulationInput, config: BackendOptions) -> PreparedCase: ...

    def run_case(self, prepared: PreparedCase, config: BackendOptions) -> RawRunResult: ...

    def parse_results(self, raw: RawRunResult, prepared: PreparedCase) -> SimulationResult: ...

    def parse_existing(self, output_path: Path, config: BackendOptions) -> SimulationResult: ...

