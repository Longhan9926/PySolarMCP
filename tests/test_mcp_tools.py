from __future__ import annotations

from pathlib import Path

import pytest

from solarcell_sim_mcp.server import main as mcp_main
from solarcell_sim_mcp.tools import solarcell_prepare_case, solarcell_validate_input

from tests.conftest import sample_case


def test_mcp_validate_input_hides_backend_options(baseline_definition: Path, tmp_path: Path) -> None:
    case = sample_case(baseline_definition, tmp_path / "client-runs")

    result = solarcell_validate_input(case, backend="scaps")

    assert result["errors"] == []
    assert result["normalizedInput"]["backend"] == "scaps"
    assert "backendOptions" not in result["normalizedInput"]


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
