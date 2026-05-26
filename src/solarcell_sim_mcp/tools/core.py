from __future__ import annotations

from pathlib import Path
from typing import Any

from solarcell_sim import api


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


def solarcell_check_backend(backend: str = "scaps") -> dict[str, Any]:
    """Check a server-managed simulation backend.

    MCP clients choose only the backend name. Executable paths, definition files,
    Wine settings, and work directories are loaded from the remote server's
    environment or config files.
    """
    status = api.check_backend(backend=backend)
    return status.model_dump(mode="json", by_alias=True)


def solarcell_validate_input(case: dict[str, Any], backend: str | None = None) -> dict[str, Any]:
    """Validate physical simulation input using the selected server backend.

    Do not send backendOptions from an MCP client; any supplied backendOptions are
    ignored so the remote server remains the source of runtime configuration.
    """
    report = api.validate_input(_mcp_case(case, backend=backend))
    return _hide_backend_options(report.model_dump(mode="json", by_alias=True))


def solarcell_prepare_case(case: dict[str, Any], backend: str | None = None) -> dict[str, Any]:
    """Prepare a simulation case using server-side backend configuration."""
    result = api.prepare_case(_mcp_case(case, backend=backend))
    return result.model_dump(mode="json", by_alias=True)


def solarcell_run_case(case: dict[str, Any], backend: str | None = None) -> dict[str, Any]:
    """Run a simulation case using server-side backend configuration."""
    result = api.run_case(_mcp_case(case, backend=backend))
    return result.model_dump(mode="json", by_alias=True)


def solarcell_run_sweep(case: dict[str, Any], backend: str | None = None) -> dict[str, Any]:
    """Run a parameter sweep using server-side backend configuration."""
    return api.run_sweep(_mcp_case(case, backend=backend))


def solarcell_parse_results(output_path: str, backend: str = "scaps") -> dict[str, Any]:
    """Parse an existing output file with server-side backend configuration."""
    result = api.parse_results(Path(output_path), backend=backend)
    return result.model_dump(mode="json", by_alias=True)


def solarcell_get_artifact(run_id: str, artifact_type: str | None = None) -> dict[str, Any]:
    """Return artifacts for a run from the server-configured work directory."""
    return api.get_artifact(run_id, artifact_type=artifact_type)
