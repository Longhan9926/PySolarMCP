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


def test_config_reads_project_dotenv(tmp_path: Path, baseline_definition: Path) -> None:
    executable = tmp_path / "scaps.exe"
    executable.write_text("", encoding="utf-8")
    wine_prefix = tmp_path / "wineprefix"
    (tmp_path / ".env").write_text(
        f"""
# Comments and optional export prefixes are supported.
export SCAPS_EXECUTABLE_PATH={executable}
SCAPS_DEFINITION_PATH="{baseline_definition}"
SCAPS_WORKDIR={tmp_path / 'runs'} # inline comment
SCAPS_RUNTIME_STRATEGY=workspace_copy
WINE_BIN=wine-from-dotenv
WINEPREFIX={wine_prefix}
WINEARCH=win32
SOLARCELL_SIM_XVFB=true
""",
        encoding="utf-8",
    )

    options = load_backend_options("scaps", cwd=tmp_path)

    assert options.executable_path == executable
    assert options.definition_source is not None
    assert options.definition_source.path == baseline_definition
    assert options.workdir == tmp_path / "runs"
    assert options.runtime_strategy == "workspace_copy"
    assert options.wine_bin == "wine-from-dotenv"
    assert options.wine_prefix == wine_prefix
    assert options.wine_arch == "win32"
    assert options.use_xvfb is True


def test_dotenv_relative_paths_resolve_from_cwd(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "SCAPS_EXECUTABLE_PATH=external/scaps/scaps.exe",
                "SCAPS_DEFINITION_PATH=external/definitions/baseline.scaps",
                "SCAPS_WORKDIR=runs",
                "WINEPREFIX=wineprefix",
            ]
        ),
        encoding="utf-8",
    )

    options = load_backend_options("scaps", cwd=tmp_path)

    assert options.executable_path == tmp_path / "external" / "scaps" / "scaps.exe"
    assert options.definition_source is not None
    assert options.definition_source.path == tmp_path / "external" / "definitions" / "baseline.scaps"
    assert options.workdir == tmp_path / "runs"
    assert options.wine_prefix == tmp_path / "wineprefix"


def test_process_env_overrides_project_dotenv(monkeypatch, tmp_path: Path, baseline_definition: Path) -> None:
    dotenv_exe = tmp_path / "dotenv.exe"
    dotenv_exe.write_text("", encoding="utf-8")
    env_exe = tmp_path / "env.exe"
    env_exe.write_text("", encoding="utf-8")
    (tmp_path / ".env").write_text(
        f"SCAPS_EXECUTABLE_PATH={dotenv_exe}\nSCAPS_DEFINITION_PATH={baseline_definition}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SCAPS_EXECUTABLE_PATH", str(env_exe))

    options = load_backend_options("scaps", cwd=tmp_path)

    assert options.executable_path == env_exe
    assert options.definition_source is not None
    assert options.definition_source.path == baseline_definition

