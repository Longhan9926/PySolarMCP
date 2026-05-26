from __future__ import annotations

import itertools
from copy import deepcopy
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from solarcell_sim.backends.registry import get_backend
from solarcell_sim.config import load_backend_options
from solarcell_sim.errors import SolarCellSimError
from solarcell_sim.schema import (
    ArtifactRef,
    BackendOptions,
    BackendStatus,
    Diagnostic,
    PreparedCase,
    RawRunResult,
    SimulationCurves,
    SimulationInput,
    SimulationResult,
    ValidationReport,
)
from solarcell_sim.storage import read_json


def _error_result(run_id: str, backend: str, runner: str, status: str, diagnostics: list[Diagnostic]) -> SimulationResult:
    return SimulationResult(
        run_id=run_id,
        backend=backend,
        runner=runner,
        status=status,  # type: ignore[arg-type]
        diagnostics=diagnostics,
    )


def _coerce_case(case: SimulationInput | dict[str, Any]) -> SimulationInput:
    if isinstance(case, SimulationInput):
        return case
    return SimulationInput.model_validate(case)


def _coerce_options(options: BackendOptions | dict[str, Any] | None) -> BackendOptions | dict[str, Any] | None:
    return options


def check_backend(
    backend: str = "scaps",
    backend_options: BackendOptions | dict[str, Any] | None = None,
    cwd: Path | None = None,
) -> BackendStatus:
    options = load_backend_options(backend, _coerce_options(backend_options), cwd=cwd)
    return get_backend(backend).check_available(options)


def validate_input(case: SimulationInput | dict[str, Any]) -> ValidationReport:
    try:
        parsed = _coerce_case(case)
    except PydanticValidationError as exc:
        return ValidationReport(
            errors=[
                Diagnostic(severity="error", code="schema.validation_error", message=str(exc))
            ]
        )
    return get_backend(parsed.backend).validate_input(parsed)


def prepare_case(case: SimulationInput | dict[str, Any], cwd: Path | None = None) -> SimulationResult:
    try:
        parsed = _coerce_case(case)
        options = load_backend_options(parsed.backend, parsed.backend_options, cwd=cwd)
        prepared = get_backend(parsed.backend).prepare_case(parsed, options)
        return SimulationResult(
            run_id=prepared.run_id,
            backend=parsed.backend,
            runner=options.runner,
            status="prepared",
            diagnostics=prepared.diagnostics,
            artifacts=prepared.artifacts,
        )
    except PydanticValidationError as exc:
        return _error_result(
            "validation-error",
            "unknown",
            "unknown",
            "failed",
            [Diagnostic(severity="error", code="schema.validation_error", message=str(exc))],
        )
    except SolarCellSimError as exc:
        return _error_result("prepare-error", "scaps", "unknown", "config_required", exc.diagnostics)


def prepare_case_internal(case: SimulationInput | dict[str, Any], cwd: Path | None = None) -> PreparedCase:
    parsed = _coerce_case(case)
    options = load_backend_options(parsed.backend, parsed.backend_options, cwd=cwd)
    return get_backend(parsed.backend).prepare_case(parsed, options)


def run_case(case: SimulationInput | dict[str, Any], cwd: Path | None = None) -> SimulationResult:
    try:
        parsed = _coerce_case(case)
        options = load_backend_options(parsed.backend, parsed.backend_options, cwd=cwd)
        backend = get_backend(parsed.backend)
        prepared = backend.prepare_case(parsed, options)
        raw = backend.run_case(prepared, options)
        return backend.parse_results(raw, prepared)
    except PydanticValidationError as exc:
        return _error_result(
            "validation-error",
            "unknown",
            "unknown",
            "failed",
            [Diagnostic(severity="error", code="schema.validation_error", message=str(exc))],
        )
    except SolarCellSimError as exc:
        return _error_result("run-error", "scaps", "unknown", "config_required", exc.diagnostics)


def _aggregate_status(statuses: list[str]) -> str:
    if not statuses:
        return "failed"
    unique = set(statuses)
    if unique == {"success"}:
        return "success"
    if unique == {"config_required"}:
        return "config_required"
    if unique == {"failed"}:
        return "failed"
    return "partial"


def _set_path(data: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    result = deepcopy(data)
    cursor: Any = result
    parts = path.split(".")
    for part in parts[:-1]:
        if part.endswith("]"):
            name, index_text = part[:-1].split("[")
            cursor = cursor[name][int(index_text)]
        else:
            cursor = cursor[part]
    last = parts[-1]
    if last.endswith("]"):
        name, index_text = last[:-1].split("[")
        cursor[name][int(index_text)] = value
    else:
        cursor[last] = value
    return result


def run_sweep(case: SimulationInput | dict[str, Any], cwd: Path | None = None) -> dict[str, Any]:
    parsed = _coerce_case(case)
    if parsed.sweep is None:
        result = run_case(parsed, cwd=cwd)
        return {"status": result.status, "results": [result.model_dump(mode="json", by_alias=True)]}

    base = parsed.model_dump(mode="json", by_alias=True)
    variables = parsed.sweep.variables
    results: list[dict[str, Any]] = []
    for values in itertools.product(*(variable.values for variable in variables)):
        candidate = base
        tags = []
        for variable, value in zip(variables, values, strict=True):
            candidate = _set_path(candidate, variable.path, value)
            tags.append({"path": variable.path, "value": value})
        result = run_case(candidate, cwd=cwd)
        row = result.model_dump(mode="json", by_alias=True)
        row["sweepValues"] = tags
        results.append(row)
    return {"status": _aggregate_status([str(item.get("status")) for item in results]), "results": results}


def parse_results(
    output_path: str | Path,
    backend: str = "scaps",
    backend_options: BackendOptions | dict[str, Any] | None = None,
    cwd: Path | None = None,
) -> SimulationResult:
    options = load_backend_options(backend, _coerce_options(backend_options), cwd=cwd)
    return get_backend(backend).parse_existing(Path(output_path), options)


def get_artifact(run_id: str, artifact_type: str | None = None, backend_options: BackendOptions | dict[str, Any] | None = None) -> dict[str, Any]:
    options = load_backend_options("scaps", _coerce_options(backend_options))
    if options.workdir is None:
        return {"status": "config_required", "diagnostics": ["SCAPS workdir is not configured"]}
    manifest = options.workdir / run_id / "manifest.json"
    if not manifest.exists():
        return {"status": "failed", "diagnostics": [f"Run manifest not found: {manifest}"]}
    data = read_json(manifest)
    artifacts = data.get("artifacts", [])
    if artifact_type:
        artifacts = [item for item in artifacts if item.get("type") == artifact_type]
    return {"status": "success", "runId": run_id, "artifacts": artifacts, "manifest": data}

