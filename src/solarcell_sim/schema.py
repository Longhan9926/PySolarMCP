from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def to_camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


class SolarModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        arbitrary_types_allowed=True,
        populate_by_name=True,
        use_enum_values=True,
    )


class Diagnostic(SolarModel):
    severity: Literal["info", "warning", "error"]
    code: str
    message: str


class ValidationReport(SolarModel):
    errors: list[Diagnostic] = Field(default_factory=list)
    warnings: list[Diagnostic] = Field(default_factory=list)
    normalized_input: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return not self.errors


class DefinitionSource(SolarModel):
    type: Literal["baseline_file", "generated", "template"] = "baseline_file"
    path: Path | None = None
    template_name: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "DefinitionSource":
        if self.type == "baseline_file" and self.path is None:
            raise ValueError("baseline_file definition source requires path")
        if self.type == "template" and not self.template_name:
            raise ValueError("template definition source requires templateName")
        return self


class BackendOptions(SolarModel):
    runner: Literal["wine", "windows_native", "direct"] = "wine"
    executable_path: Path | None = None
    workdir: Path | None = None
    definition_source: DefinitionSource | None = None
    wine_bin: str = "wine"
    wine_prefix: Path | None = None
    use_xvfb: bool | None = None
    xvfb_bin: str = "xvfb-run"
    timeout_seconds: int = 120
    runtime_strategy: Literal["workspace_link", "workspace_copy", "in_place"] = "workspace_link"
    extra_args: list[str] = Field(default_factory=list)

    @field_validator("timeout_seconds")
    @classmethod
    def validate_timeout(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("timeoutSeconds must be positive")
        return value


class SimulationDefect(SolarModel):
    name: str | None = None
    density_cm3: float | None = None
    energy_ev: float | None = None
    kind: str | None = None


class SimulationMaterial(SolarModel):
    bandgap_ev: float
    electron_affinity_ev: float
    relative_permittivity: float
    nc_cm3: float | None = None
    nv_cm3: float | None = None
    electron_mobility_cm2_vs: float | None = None
    hole_mobility_cm2_vs: float | None = None
    donor_density_cm3: float | None = None
    acceptor_density_cm3: float | None = None
    absorption_file: str | None = None


class SimulationLayer(SolarModel):
    name: str
    role: Literal["TCO", "ETL", "absorber", "HTL", "metal", "other"]
    thickness_nm: float
    material: SimulationMaterial
    defects: list[SimulationDefect] = Field(default_factory=list)


class SimulationContact(SolarModel):
    name: str | None = None
    work_function_ev: float | None = None
    surface_recombination_velocity_cm_s: float | None = None


class SimulationDevice(SolarModel):
    architecture: Literal["n-i-p", "p-i-n", "custom"]
    layers: list[SimulationLayer]
    front_contact: SimulationContact = Field(default_factory=SimulationContact)
    back_contact: SimulationContact = Field(default_factory=SimulationContact)


class VoltageScan(SolarModel):
    start_v: float
    stop_v: float
    step_v: float

    @model_validator(mode="after")
    def validate_scan(self) -> "VoltageScan":
        if self.step_v == 0:
            raise ValueError("stepV must be non-zero")
        if (self.stop_v - self.start_v) * self.step_v <= 0:
            raise ValueError("stepV sign must move from startV toward stopV")
        return self


class SimulationConditions(SolarModel):
    temperature_k: float
    illumination: Literal["AM1.5G", "custom", "dark"]
    incident_side: Literal["front", "back"]
    voltage_scan: VoltageScan


class SweepVariable(SolarModel):
    path: str
    values: list[float | int | str]

    @field_validator("values")
    @classmethod
    def validate_values(cls, value: list[float | int | str]) -> list[float | int | str]:
        if not value:
            raise ValueError("sweep variable values cannot be empty")
        return value


class SimulationSweep(SolarModel):
    variables: list[SweepVariable]


class Provenance(SolarModel):
    parameter_sources: list[str] = Field(default_factory=list)
    notes: str | None = None


class SimulationInput(SolarModel):
    name: str
    backend: Literal["scaps", "wxamps", "setfos", "custom_python", "surrogate_model"] = "scaps"
    backend_options: BackendOptions = Field(default_factory=BackendOptions)
    device: SimulationDevice
    conditions: SimulationConditions
    measurements: list[Literal["JV", "QE", "CV", "CF", "BANDS"]] = Field(default_factory=lambda: ["JV"])
    sweep: SimulationSweep | None = None
    provenance: Provenance | None = None


class ArtifactRef(SolarModel):
    type: Literal["input", "raw_output", "parsed_csv", "parsed_json", "plot", "log", "manifest", "script", "definition"]
    path: str
    description: str | None = None


class TableRef(SolarModel):
    path: str
    columns: list[str] = Field(default_factory=list)
    rows: int | None = None


class SimulationMetrics(SolarModel):
    pce_percent: float | None = None
    voc_v: float | None = None
    jsc_ma_cm2: float | None = None
    ff_percent: float | None = None
    vmpp_v: float | None = None
    jmpp_ma_cm2: float | None = None
    extrapolated: bool = False


class SimulationCurves(SolarModel):
    jv: TableRef | None = None
    qe: TableRef | None = None
    cv: TableRef | None = None
    cf: TableRef | None = None


class SimulationProfiles(SolarModel):
    bands: TableRef | None = None
    recombination: TableRef | None = None
    electric_field: TableRef | None = None
    carrier_density: TableRef | None = None


class EnvironmentInfo(SolarModel):
    executable_path: str | None = None
    wine_bin: str | None = None
    wine_prefix: str | None = None
    runner: str | None = None


class SimulationResult(SolarModel):
    run_id: str
    backend: str
    backend_version: str | None = None
    runner: str
    status: Literal["success", "failed", "partial", "config_required", "prepared"]
    metrics: SimulationMetrics | None = None
    curves: SimulationCurves | None = None
    profiles: SimulationProfiles | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    environment: EnvironmentInfo | None = None


class BackendStatus(SolarModel):
    backend: str
    status: Literal["available", "config_required", "unavailable"]
    runner: str
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    executable_path: str | None = None
    definition_path: str | None = None
    workdir: str | None = None
    wine_bin: str | None = None
    wine_prefix: str | None = None


class DefinitionArtifact(SolarModel):
    source_type: Literal["baseline_file", "generated", "template"]
    path: Path
    hash: str


class ScriptArtifact(SolarModel):
    path: Path
    hash: str
    warnings: list[Diagnostic] = Field(default_factory=list)


class PreparedCase(SolarModel):
    run_id: str
    workdir: Path
    scaps_root: Path
    definition: DefinitionArtifact
    script: ScriptArtifact
    result_file: Path
    manifest_path: Path
    backend_options: BackendOptions
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class RawRunResult(SolarModel):
    run_id: str
    status: Literal["success", "failed", "partial", "config_required"]
    stdout: str = ""
    stderr: str = ""
    return_code: int | None = None
    result_file: Path | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)

