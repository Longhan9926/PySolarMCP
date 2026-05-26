from __future__ import annotations

from pathlib import Path

from solarcell_sim.config import load_backend_options
from solarcell_sim.schema import SimulationInput

from tests.conftest import sample_case


def test_schema_round_trips_camel_case(baseline_definition: Path, tmp_path: Path) -> None:
    case = SimulationInput.model_validate(sample_case(baseline_definition, tmp_path / "runs"))

    dumped = case.model_dump(mode="json", by_alias=True)

    assert dumped["backendOptions"]["definitionSource"]["type"] == "baseline_file"
    assert dumped["conditions"]["voltageScan"]["stepV"] == 0.05
    assert dumped["device"]["layers"][0]["thicknessNm"] == 25


def test_config_priority_project_over_env(monkeypatch, tmp_path: Path, baseline_definition: Path) -> None:
    env_exe = tmp_path / "env.exe"
    env_exe.write_text("", encoding="utf-8")
    project_exe = tmp_path / "project.exe"
    project_exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("SCAPS_EXECUTABLE_PATH", str(env_exe))
    monkeypatch.setenv("SCAPS_DEFINITION_PATH", str(baseline_definition))
    (tmp_path / ".solarcell-sim.toml").write_text(
        f"""
[backends.scaps]
runner = "direct"
executable_path = "{project_exe}"
workdir = "{tmp_path / 'runs'}"

[backends.scaps.wine]
bin = "wine-from-project"
""",
        encoding="utf-8",
    )

    options = load_backend_options("scaps", cwd=tmp_path)

    assert options.executable_path == project_exe
    assert options.runner == "direct"
    assert options.definition_source is not None
    assert options.definition_source.path == baseline_definition

