from __future__ import annotations

from pathlib import Path
import threading
from typing import Any

from solarcell_sim import api
from solarcell_sim.schema import Diagnostic
from solarcell_sim_mcp import mock


_RUN_LOCK = threading.Lock()
SCAPS_RUN_POLICY = {
    "maxConcurrentRuns": 1,
    "queueing": "none",
    "busyDiagnosticCode": "mcp.run_busy",
    "clientGuidance": (
        "The SCAPS backend is serialized on this MCP server. Do not start another "
        "solarcell_run_case call until the active run has finished; concurrent "
        "requests return mcp.run_busy and are not queued."
    ),
}


def _run_policy(backend: str) -> dict[str, Any]:
    if backend == "scaps":
        return dict(SCAPS_RUN_POLICY)
    return {"maxConcurrentRuns": None, "queueing": "unspecified"}


def _strip_backend_options(data: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(data)
    cleaned.pop("backendOptions", None)
    cleaned.pop("backend_options", None)
    return cleaned


def _mcp_case(case: dict[str, Any], backend: str | None = None) -> dict[str, Any]:
    cleaned = _strip_backend_options(case)
    selected_backend = backend or cleaned.get("backend") or "scaps"
    cleaned["backend"] = selected_backend
    return cleaned


def _hide_backend_options(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned = _strip_backend_options(payload)
    normalized = cleaned.get("normalizedInput")
    if isinstance(normalized, dict):
        cleaned["normalizedInput"] = _strip_backend_options(normalized)
    return cleaned


def _run_busy_result(backend: str) -> dict[str, Any]:
    diagnostic = Diagnostic(
        severity="error",
        code="mcp.run_busy",
        message=(
            "Another SCAPS simulation is already running on this MCP server. "
            "Retry only after that run finishes; do not retry the same request in a tight loop."
        ),
    )
    return {
        "runId": "mcp-busy",
        "backend": backend,
        "runner": "unknown",
        "status": "failed",
        "runPolicy": _run_policy(backend),
        "diagnostics": [diagnostic.model_dump(mode="json", by_alias=True)],
        "artifacts": [],
    }


def solarcell_check_backend(backend: str = "scaps") -> dict[str, Any]:
    """Check a server-managed simulation backend.

    MCP clients choose only the backend name. Executable paths, definition files,
    Wine settings, and work directories are loaded from the remote server's
    environment or config files. For SCAPS, only one solarcell_run_case call may
    run at a time; concurrent run requests return mcp.run_busy and are not queued.
    """
    if mock.enabled():
        payload = mock.check_backend(backend=backend)
        payload["runPolicy"] = _run_policy(backend)
        return payload
    status = api.check_backend(backend=backend)
    payload = status.model_dump(mode="json", by_alias=True)
    payload["runPolicy"] = _run_policy(backend)
    return payload


def solarcell_get_baseline_run(architecture: str = "p-i-n", backend: str = "scaps") -> dict[str, Any]:
    """Return a baseline run request for architecture p-i-n or n-i-p.

    The returned case intentionally excludes backendOptions. MCP clients can pass
    it directly to solarcell_validate_input, solarcell_prepare_case, or
    solarcell_run_case; server-side configuration supplies SCAPS paths. For
    SCAPS, run calls are serialized and concurrent requests return mcp.run_busy.
    """
    if mock.enabled():
        payload = mock.get_baseline_run(architecture=architecture, backend=backend)
        payload["runPolicy"] = _run_policy(backend)
        return payload
    try:
        case = api.get_baseline_case(architecture=architecture, backend=backend)
    except ValueError as exc:
        diagnostic = Diagnostic(severity="error", code="baseline.architecture_unsupported", message=str(exc))
        return {
            "status": "failed",
            "backend": backend,
            "architecture": architecture,
            "case": None,
            "runPolicy": _run_policy(backend),
            "diagnostics": [diagnostic.model_dump(mode="json", by_alias=True)],
        }

    report = api.validate_input(case)
    validation = _hide_backend_options(report.model_dump(mode="json", by_alias=True))
    return {
        "status": "success" if report.ok else "failed",
        "backend": backend,
        "architecture": architecture,
        "case": _strip_backend_options(case),
        "runPolicy": _run_policy(backend),
        "validation": validation,
        "diagnostics": validation.get("errors", []),
    }


def solarcell_validate_input(case: dict[str, Any], backend: str | None = None) -> dict[str, Any]:
    """Validate physical simulation input using the selected server backend.

    Do not send backendOptions from an MCP client; any supplied backendOptions are
    ignored so the remote server remains the source of runtime configuration.
    """
    if mock.enabled():
        return mock.validate_input(_mcp_case(case, backend=backend), backend=backend)
    report = api.validate_input(_mcp_case(case, backend=backend))
    return _hide_backend_options(report.model_dump(mode="json", by_alias=True))


def solarcell_prepare_case(case: dict[str, Any], backend: str | None = None) -> dict[str, Any]:
    """Prepare a simulation case using server-side backend configuration."""
    if mock.enabled():
        payload = mock.prepare_case(_mcp_case(case, backend=backend), backend=backend)
        payload["runPolicy"] = _run_policy(backend or payload.get("backend") or "scaps")
        return payload
    result = api.prepare_case(_mcp_case(case, backend=backend))
    return result.model_dump(mode="json", by_alias=True)


def solarcell_run_case(case: dict[str, Any], backend: str | None = None) -> dict[str, Any]:
    """Run one simulation case using server-side backend configuration.

    The SCAPS backend is serialized on this MCP server: only one
    solarcell_run_case call may run at a time. Concurrent requests are not queued
    and return mcp.run_busy.

    Agents should call solarcell_validate_input first. Validation errors will fail
    without launching SCAPS; validation warnings are returned but do not block a
    run. If this tool returns mcp.run_busy or runner.timeout, do not immediately
    retry the same request.
    """
    prepared_case = _mcp_case(case, backend=backend)
    selected_backend = str(prepared_case.get("backend") or "scaps")
    if mock.enabled():
        payload = mock.run_case(prepared_case, backend=backend)
        payload["runPolicy"] = _run_policy(selected_backend)
        return payload
    if not _RUN_LOCK.acquire(blocking=False):
        return _run_busy_result(selected_backend)
    try:
        result = api.run_case(prepared_case)
        payload = result.model_dump(mode="json", by_alias=True)
        payload["runPolicy"] = _run_policy(selected_backend)
        return payload
    finally:
        _RUN_LOCK.release()


def solarcell_parse_results(output_path: str, backend: str = "scaps") -> dict[str, Any]:
    """Parse an existing output file with server-side backend configuration."""
    if mock.enabled():
        return mock.parse_results(output_path, backend=backend)
    result = api.parse_results(Path(output_path), backend=backend)
    return result.model_dump(mode="json", by_alias=True)


def solarcell_get_artifact(run_id: str, artifact_type: str | None = None) -> dict[str, Any]:
    """Return artifacts for a run from the server-configured work directory."""
    if mock.enabled():
        return mock.get_artifact(run_id, artifact_type=artifact_type)
    return api.get_artifact(run_id, artifact_type=artifact_type)


def solarcell_build_layer_material_from_card(
    card: dict[str, Any],
    base_material: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert a MatContractServer SCAPS material card to a PySolarMCP layer material."""
    if mock.enabled():
        return mock.build_layer_material_from_card(card, base_material=base_material)
    return api.build_layer_material_from_scaps_card(card, base_material=base_material)


def solarcell_apply_scaps_material_card(
    case: dict[str, Any],
    card: dict[str, Any],
    layer_name: str | None = None,
    layer_index: int | None = None,
    role: str | None = None,
    preserve_existing: bool = True,
) -> dict[str, Any]:
    """Apply a SCAPS material card to one layer in a simulation case."""
    if mock.enabled():
        return mock.apply_scaps_material_card(
            _mcp_case(case),
            card,
            layer_name=layer_name,
            layer_index=layer_index,
            role=role,
            preserve_existing=preserve_existing,
        )
    return api.apply_scaps_material_card_to_case(
        _mcp_case(case),
        card,
        layer_name=layer_name,
        layer_index=layer_index,
        role=role,
        preserve_existing=preserve_existing,
    )
