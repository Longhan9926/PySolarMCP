from __future__ import annotations

from pathlib import Path

from solarcell_sim_mcp.tools import solarcell_prepare_case, solarcell_validate_input

from tests.conftest import sample_case


def test_mcp_validate_input_returns_json_dict(baseline_definition: Path, tmp_path: Path) -> None:
    result = solarcell_validate_input(sample_case(baseline_definition, tmp_path / "runs"))

    assert result["errors"] == []
    assert result["normalizedInput"]["backend"] == "scaps"


def test_mcp_prepare_case_returns_artifacts(baseline_definition: Path, fake_executable: Path, tmp_path: Path) -> None:
    result = solarcell_prepare_case(sample_case(baseline_definition, tmp_path / "runs", executable=fake_executable))

    assert result["status"] == "prepared"
    assert any(item["type"] == "script" for item in result["artifacts"])

