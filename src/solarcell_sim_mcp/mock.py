from __future__ import annotations

import os
import random
from copy import deepcopy
from typing import Any
from uuid import uuid4

from pydantic import ValidationError as PydanticValidationError

from solarcell_sim import api
from solarcell_sim.schema import (
    ArtifactRef,
    BackendStatus,
    Diagnostic,
    EnvironmentInfo,
    ExecutionInfo,
    SimulationCurves,
    SimulationInput,
    SimulationMetrics,
    SimulationOutput,
    SimulationResult,
    TableRef,
    ValidationReport,
)


_TRUE_VALUES = {"1", "true", "yes", "on", "mock"}


def enabled() -> bool:
    return (
        _truthy(os.getenv("MCP_MOCK_MODE"))
        or _truthy(os.getenv("SOLARCELL_SIM_MOCK_MODE"))
        or _truthy(os.getenv("PYSOLAR_MOCK_MODE"))
    )


def check_backend(backend: str = "scaps") -> dict[str, Any]:
    status = BackendStatus(
        backend=backend,
        status="available",
        runner="mock",
        diagnostics=[_diagnostic()],
        executablePath="mock://scaps/scaps.exe",
        definitionPath="mock://scaps/definitions/baseline.scaps",
        workdir="mock://solarcell-sim/runs",
    )
    payload = status.model_dump(mode="json", by_alias=True)
    return payload


def get_baseline_run(architecture: str = "p-i-n", backend: str = "scaps") -> dict[str, Any]:
    try:
        case = api.get_baseline_case(architecture=architecture, backend=backend)
    except ValueError:
        case = _baseline_case(architecture=architecture, backend=backend)
    case = deepcopy(case)
    case.pop("backendOptions", None)
    case.pop("backend_options", None)
    validation = validate_input(case, backend=backend)
    return {
        "status": "success",
        "backend": backend,
        "architecture": architecture,
        "case": case,
        "validation": validation,
        "diagnostics": [_diagnostic().model_dump(mode="json", by_alias=True)],
        "mock": True,
    }


def validate_input(case: dict[str, Any], backend: str | None = None) -> dict[str, Any]:
    normalized = deepcopy(case)
    normalized["backend"] = backend or normalized.get("backend") or "scaps"
    normalized.pop("backendOptions", None)
    normalized.pop("backend_options", None)
    try:
        parsed = SimulationInput.model_validate(normalized)
        normalized = parsed.model_dump(mode="json", by_alias=True)
        errors: list[Diagnostic] = []
    except PydanticValidationError as exc:
        errors = [Diagnostic(severity="error", code="schema.validation_error", message=str(exc))]
    report = ValidationReport(
        errors=errors,
        warnings=[] if errors else [_diagnostic()],
        normalizedInput=None if errors else normalized,
    )
    payload = report.model_dump(mode="json", by_alias=True)
    return payload


def prepare_case(case: dict[str, Any], backend: str | None = None) -> dict[str, Any]:
    result = _result(status="prepared", case=case, backend=backend)
    payload = result.model_dump(mode="json", by_alias=True)
    return payload


def run_case(case: dict[str, Any], backend: str | None = None) -> dict[str, Any]:
    result = _result(status="success", case=case, backend=backend, include_metrics=True)
    payload = result.model_dump(mode="json", by_alias=True)
    return payload


def parse_results(output_path: str, backend: str = "scaps") -> dict[str, Any]:
    result = _result(status="success", case={"backend": backend}, backend=backend, include_metrics=True)
    payload = result.model_dump(mode="json", by_alias=True)
    payload["artifacts"].append({"type": "raw_output", "path": output_path, "description": "Mock parsed output"})
    return payload


def get_artifact(run_id: str, artifact_type: str | None = None) -> dict[str, Any]:
    artifacts = [
        {"type": "raw_output", "path": f"mock://solarcell-sim/{run_id}/raw/jv.txt"},
        {"type": "parsed_json", "path": f"mock://solarcell-sim/{run_id}/parsed/metrics.json"},
        {"type": "manifest", "path": f"mock://solarcell-sim/{run_id}/manifest.json"},
    ]
    if artifact_type:
        artifacts = [artifact for artifact in artifacts if artifact["type"] == artifact_type]
    return {
        "status": "success",
        "runId": run_id,
        "artifacts": artifacts,
        "manifest": {"runId": run_id, "mock": True, "artifacts": artifacts},
        "mock": True,
    }


def build_layer_material_from_card(
    card: dict[str, Any],
    base_material: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if card.get("scapsFields"):
        return api.build_layer_material_from_scaps_card(card, base_material=base_material)
    material = dict(base_material or {})
    material.update(
        {
            "bandgapEv": _rounded(1.1, 2.3),
            "electronAffinityEv": _rounded(3.2, 4.6),
            "relativePermittivity": _rounded(6.0, 35.0),
            "electronMobilityCm2Vs": _rounded(1.0, 150.0),
            "holeMobilityCm2Vs": _rounded(0.5, 100.0),
        }
    )
    material["mock"] = True
    return material


def apply_scaps_material_card(
    case: dict[str, Any],
    card: dict[str, Any],
    layer_name: str | None = None,
    layer_index: int | None = None,
    role: str | None = None,
    preserve_existing: bool = True,
) -> dict[str, Any]:
    try:
        result = api.apply_scaps_material_card_to_case(
            case,
            card,
            layer_name=layer_name,
            layer_index=layer_index,
            role=role,
            preserve_existing=preserve_existing,
        )
    except Exception as exc:
        return {
            "status": "failed",
            "case": case,
            "diagnostics": [
                Diagnostic(
                    severity="error",
                    code="mock.material_card_apply_failed",
                    message=str(exc),
                ).model_dump(mode="json", by_alias=True)
            ],
            "mock": True,
        }
    result["mock"] = True
    result.setdefault("diagnostics", []).append(_diagnostic().model_dump(mode="json", by_alias=True))
    return result


def _result(
    *,
    status: str,
    case: dict[str, Any],
    backend: str | None,
    include_metrics: bool = False,
) -> SimulationResult:
    run_id = f"smock_{uuid4().hex[:12]}"
    backend_name = backend or case.get("backend") or "scaps"
    artifacts = [
        ArtifactRef(type="input", path=f"mock://solarcell-sim/{run_id}/input.json"),
        ArtifactRef(type="script", path=f"mock://solarcell-sim/{run_id}/run.scaps.script"),
        ArtifactRef(type="manifest", path=f"mock://solarcell-sim/{run_id}/manifest.json"),
    ]
    metrics = _metrics() if include_metrics else None
    curves = (
        SimulationCurves(
            jv=TableRef(
                path=f"mock://solarcell-sim/{run_id}/parsed/jv.csv",
                columns=["voltageV", "currentDensityMaCm2"],
                rows=random.randint(20, 40),
            )
        )
        if include_metrics
        else None
    )
    output = (
        SimulationOutput(
            stdout="Mock SCAPS run completed.",
            stderr="",
            resultText="Mock JV output generated by solarcell-sim MCP mock mode.",
        )
        if include_metrics
        else None
    )
    return SimulationResult(
        runId=run_id,
        backend=backend_name,
        backendVersion="mock",
        runner="mock",
        status=status,  # type: ignore[arg-type]
        metrics=metrics,
        curves=curves,
        diagnostics=[_diagnostic()],
        artifacts=artifacts,
        environment=EnvironmentInfo(runner="mock"),
        execution=ExecutionInfo(
            rawStatus="success" if status == "prepared" else status,  # type: ignore[arg-type]
            returnCode=0,
            runtimeCleaned=True,
        ),
        output=output,
    )


def _metrics() -> SimulationMetrics:
    voc = _rounded(0.75, 1.25)
    jsc = _rounded(15.0, 28.0)
    ff = _rounded(65.0, 86.0)
    pce = round(voc * jsc * ff / 100.0, 4)
    return SimulationMetrics(
        pcePercent=pce,
        vocV=voc,
        jscMaCm2=jsc,
        ffPercent=ff,
        vmppV=round(voc * random.uniform(0.72, 0.85), 4),
        jmppMaCm2=round(jsc * random.uniform(0.78, 0.92), 4),
    )


def _baseline_case(architecture: str = "p-i-n", backend: str = "scaps") -> dict[str, Any]:
    layers = [
        _layer("HTL", "HTL", 100, 2.8, 2.2),
        _layer("Absorber", "absorber", 600, _rounded(1.2, 1.7), _rounded(3.6, 4.3)),
        _layer("ETL", "ETL", 25, 2.3, 4.0),
    ]
    if architecture == "n-i-p":
        layers = [layers[2], layers[1], layers[0]]
    return {
        "name": f"{architecture}-mock-baseline",
        "backend": backend,
        "device": {
            "architecture": architecture if architecture in {"p-i-n", "n-i-p"} else "custom",
            "layers": layers,
            "frontContact": {"name": "front"},
            "backContact": {"name": "back"},
        },
        "conditions": {
            "temperatureK": 300,
            "illumination": "AM1.5G",
            "incidentSide": "front",
            "voltageScan": {"startV": 0, "stopV": 1.2, "stepV": 0.05},
        },
        "measurements": ["JV"],
    }


def _layer(name: str, role: str, thickness_nm: float, bandgap: float, affinity: float) -> dict[str, Any]:
    return {
        "name": name,
        "role": role,
        "thicknessNm": thickness_nm,
        "material": {
            "bandgapEv": bandgap,
            "electronAffinityEv": affinity,
            "relativePermittivity": _rounded(3.0, 30.0),
            "electronMobilityCm2Vs": _rounded(0.001, 10.0),
            "holeMobilityCm2Vs": _rounded(0.001, 10.0),
        },
    }


def _diagnostic(message: str = "Mock mode is enabled; no SCAPS simulation was executed.") -> Diagnostic:
    return Diagnostic(severity="info", code="mock.enabled", message=message)


def _rounded(low: float, high: float) -> float:
    return round(random.uniform(low, high), 4)


def _truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in _TRUE_VALUES)
