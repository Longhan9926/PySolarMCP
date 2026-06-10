from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from solarcell_sim_mcp.server import build_server, main as mcp_main
import solarcell_sim_mcp.tools.core as tool_core
from solarcell_sim_mcp.tools import (
    solarcell_apply_scaps_material_card,
    solarcell_build_layer_material_from_card,
    solarcell_check_backend,
    solarcell_get_baseline_run,
    solarcell_prepare_case,
    solarcell_run_case,
    solarcell_validate_input,
)

from tests.conftest import sample_case


def test_mcp_check_backend_exposes_serial_run_policy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for key in (
        "SCAPS_EXECUTABLE_PATH",
        "SCAPS_DEFINITION_PATH",
        "SCAPS_WORKDIR",
        "SOLARCELL_SIM_XVFB",
        "WINE_BIN",
    ):
        monkeypatch.delenv(key, raising=False)

    result = solarcell_check_backend(backend="scaps")

    assert result["runPolicy"]["maxConcurrentRuns"] == 1
    assert result["runPolicy"]["queueing"] == "none"
    assert result["runPolicy"]["busyDiagnosticCode"] == "mcp.run_busy"


def test_mcp_validate_input_hides_backend_options(baseline_definition: Path, tmp_path: Path) -> None:
    case = sample_case(baseline_definition, tmp_path / "client-runs")

    result = solarcell_validate_input(case, backend="scaps")

    assert result["errors"] == []
    assert result["normalizedInput"]["backend"] == "scaps"
    assert "backendOptions" not in result["normalizedInput"]


def test_mcp_get_baseline_run_returns_server_safe_case() -> None:
    default_result = solarcell_get_baseline_run()
    result = solarcell_get_baseline_run(architecture="p-i-n", backend="scaps")
    nip_result = solarcell_get_baseline_run(architecture="n-i-p", backend="scaps")

    assert default_result["case"]["device"]["architecture"] == "p-i-n"
    assert result["status"] == "success"
    assert result["backend"] == "scaps"
    assert result["architecture"] == "p-i-n"
    assert result["validation"]["errors"] == []
    assert result["runPolicy"]["maxConcurrentRuns"] == 1
    assert result["runPolicy"]["busyDiagnosticCode"] == "mcp.run_busy"
    assert result["case"]["name"] == "pin-baseline"
    assert result["case"]["device"]["architecture"] == "p-i-n"
    assert result["case"]["device"]["layers"][0]["role"] == "HTL"
    assert result["case"]["device"]["layers"][2]["role"] == "ETL"
    assert "backendOptions" not in result["case"]
    assert nip_result["status"] == "success"
    assert nip_result["case"]["name"] == "nip-baseline"
    assert nip_result["case"]["device"]["architecture"] == "n-i-p"
    assert nip_result["case"]["device"]["layers"][0]["role"] == "ETL"
    assert nip_result["case"]["device"]["layers"][2]["role"] == "HTL"


def test_mcp_get_baseline_run_rejects_unsupported_architecture() -> None:
    result = solarcell_get_baseline_run(architecture="custom", backend="scaps")

    assert result["status"] == "failed"
    assert result["case"] is None
    assert result["diagnostics"][0]["code"] == "baseline.architecture_unsupported"


def test_mcp_validate_input_warns_for_risky_but_runnable_case(baseline_definition: Path, tmp_path: Path) -> None:
    case = sample_case(baseline_definition, tmp_path / "client-runs")
    case["conditions"]["temperatureK"] = 50
    case["conditions"]["voltageScan"]["stepV"] = 0.0005
    case["device"]["layers"][0]["material"]["electronMobilityCm2Vs"] = 1e6
    case["device"]["layers"][0]["material"]["donorDensityCm3"] = 1e23

    result = solarcell_validate_input(case, backend="scaps")
    warning_codes = {item["code"] for item in result["warnings"]}

    assert result["errors"] == []
    assert "conditions.temperature.extreme" in warning_codes
    assert "voltage_scan.large" in warning_codes
    assert "device.layers[0].material.electronMobilityCm2Vs.large" in warning_codes
    assert "device.layers[0].material.donorDensityCm3.large" in warning_codes


def test_mcp_run_case_returns_busy_when_another_run_is_active(baseline_definition: Path, tmp_path: Path) -> None:
    assert tool_core._RUN_LOCK.acquire(blocking=False)
    try:
        result = solarcell_run_case(sample_case(baseline_definition, tmp_path / "runs"), backend="scaps")
    finally:
        tool_core._RUN_LOCK.release()

    assert result["status"] == "failed"
    assert result["runId"] == "mcp-busy"
    assert result["runPolicy"]["maxConcurrentRuns"] == 1
    assert result["diagnostics"][0]["code"] == "mcp.run_busy"


def test_mcp_prepare_case_uses_server_config(
    baseline_definition: Path,
    fake_executable: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server_runs = tmp_path / "server-runs"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SCAPS_DEFINITION_PATH", str(baseline_definition))
    monkeypatch.setenv("SCAPS_EXECUTABLE_PATH", str(fake_executable))
    monkeypatch.setenv("SCAPS_WORKDIR", str(server_runs))
    monkeypatch.setenv("SCAPS_RUNTIME_STRATEGY", "workspace_link")

    case = sample_case(baseline_definition, tmp_path / "client-runs", executable=fake_executable)
    case["backendOptions"] = {
        "definitionSource": {"type": "baseline_file", "path": str(tmp_path / "missing.scaps")},
        "executablePath": str(tmp_path / "missing.exe"),
        "workdir": str(tmp_path / "client-runs"),
        "runtimeStrategy": "in_place",
    }

    result = solarcell_prepare_case(case, backend="scaps")

    assert result["status"] == "prepared"
    assert any(item["type"] == "script" for item in result["artifacts"])
    assert result["artifacts"][0]["path"].startswith(str(server_runs))


def test_mcp_server_streamable_http_check(capsys) -> None:
    exit_code = mcp_main([
        "--transport",
        "streamable-http",
        "--host",
        "0.0.0.0",
        "--port",
        "8001",
        "--path",
        "/mcp",
        "--check",
    ])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "streamable-http" in captured.out
    assert "http://0.0.0.0:8001/mcp" in captured.out


def test_mcp_server_does_not_register_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    registered_tools: list[str] = []

    class FakeFastMCP:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def tool(self, name: str):
            def register(func):
                registered_tools.append(name)
                return func

            return register

    fake_mcp = types.ModuleType("mcp")
    fake_server = types.ModuleType("mcp.server")
    fake_fastmcp = types.ModuleType("mcp.server.fastmcp")
    fake_fastmcp.FastMCP = FakeFastMCP
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp)
    monkeypatch.setitem(sys.modules, "mcp.server", fake_server)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_fastmcp)

    build_server()

    assert "solarcell_get_baseline_run" in registered_tools
    assert "solarcell_run_case" in registered_tools
    assert "solarcell_run_sweep" not in registered_tools
    assert "solarcell_build_layer_material_from_card" in registered_tools
    assert "solarcell_apply_scaps_material_card" in registered_tools


def test_mcp_material_card_tools(sample_case_dict: dict) -> None:
    card = {
        "scapsFields": {
            "bandgapEv": {"value": 1.52},
            "electronAffinityEv": {"value": 4.28},
            "permittivityRelative": {"value": 10.2},
        }
    }

    material = solarcell_build_layer_material_from_card(card)
    applied = solarcell_apply_scaps_material_card(sample_case_dict, card, role="absorber")

    assert material["bandgapEv"] == 1.52
    assert applied["status"] == "success"
    assert applied["case"]["device"]["layers"][1]["material"]["electronAffinityEv"] == 4.28
