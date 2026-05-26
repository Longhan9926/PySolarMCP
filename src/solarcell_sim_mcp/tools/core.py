from __future__ import annotations

from pathlib import Path
from typing import Any

from solarcell_sim import api


def solarcell_check_backend(backend: str = "scaps", backend_config: dict[str, Any] | None = None) -> dict[str, Any]:
    status = api.check_backend(backend=backend, backend_options=backend_config)
    return status.model_dump(mode="json", by_alias=True)


def solarcell_validate_input(case: dict[str, Any]) -> dict[str, Any]:
    report = api.validate_input(case)
    return report.model_dump(mode="json", by_alias=True)


def solarcell_prepare_case(case: dict[str, Any]) -> dict[str, Any]:
    result = api.prepare_case(case)
    return result.model_dump(mode="json", by_alias=True)


def solarcell_run_case(case: dict[str, Any]) -> dict[str, Any]:
    result = api.run_case(case)
    return result.model_dump(mode="json", by_alias=True)


def solarcell_run_sweep(case: dict[str, Any]) -> dict[str, Any]:
    return api.run_sweep(case)


def solarcell_parse_results(output_path: str, backend: str = "scaps", backend_config: dict[str, Any] | None = None) -> dict[str, Any]:
    result = api.parse_results(Path(output_path), backend=backend, backend_options=backend_config)
    return result.model_dump(mode="json", by_alias=True)


def solarcell_get_artifact(run_id: str, artifact_type: str | None = None, backend_config: dict[str, Any] | None = None) -> dict[str, Any]:
    return api.get_artifact(run_id, artifact_type=artifact_type, backend_options=backend_config)

