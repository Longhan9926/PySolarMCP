from __future__ import annotations

from pathlib import Path

from solarcell_sim import check_backend, parse_results, prepare_case, validate_input
from solarcell_sim.api import prepare_case_internal
from solarcell_sim.runners.wine import DirectScapsRunner

from tests.conftest import sample_case


def test_validate_input_accepts_baseline_case(baseline_definition: Path, tmp_path: Path) -> None:
    report = validate_input(sample_case(baseline_definition, tmp_path / "runs"))

    assert report.ok
    assert report.normalized_input is not None


def test_prepare_case_copies_definition_and_generates_script(baseline_definition: Path, fake_executable: Path, tmp_path: Path) -> None:
    case = sample_case(baseline_definition, tmp_path / "runs", executable=fake_executable)

    prepared_result = prepare_case(case)
    prepared = prepare_case_internal(case)

    assert prepared_result.status == "prepared"
    assert prepared.definition.path.exists()
    assert prepared.script.path.exists()
    script = prepared.script.path.read_text(encoding="utf-8")
    assert "load allscapssettingsfile baseline.scaps" in script
    assert "set layer1.thickness 0.025" in script
    assert "set layer2.defect1.Ntotal 1000000000000.0" in script
    assert "calculate singleshot" in script
    assert "save results.iv pyscaps.out" in script


def test_runner_materializes_sibling_runtime_files(baseline_definition: Path, tmp_path: Path) -> None:
    scaps_dir = tmp_path / "scaps"
    scaps_dir.mkdir()
    executable = scaps_dir / "scaps.exe"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    sibling_dll = scaps_dir / "Scapsdll.dll"
    sibling_dll.write_text("dll", encoding="utf-8")

    case = sample_case(baseline_definition, tmp_path / "runs", executable=executable)
    case["backendOptions"]["runtimeStrategy"] = "workspace_copy"
    prepared = prepare_case_internal(case)

    runtime_executable = DirectScapsRunner().materialize_runtime(prepared, prepared.backend_options)

    assert runtime_executable == prepared.scaps_root / "scaps.exe"
    assert runtime_executable.exists()
    assert (prepared.scaps_root / "Scapsdll.dll").read_text(encoding="utf-8") == "dll"


def test_check_backend_reports_missing_executable(baseline_definition: Path, tmp_path: Path) -> None:
    status = check_backend(
        backend_options={
            "runner": "direct",
            "workdir": str(tmp_path / "runs"),
            "definitionSource": {"type": "baseline_file", "path": str(baseline_definition)},
        },
        cwd=tmp_path,
    )

    assert status.status == "config_required"
    assert any(item.code == "scaps.executable_missing" for item in status.diagnostics)


def test_parse_scaps_sample_output(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "scaps_sample_outputs" / "pyscaps.out"
    target = tmp_path / "pyscaps.out"
    target.write_text(fixture.read_text(encoding="utf-8"), encoding="ISO-8859-1")

    result = parse_results(target, backend_options={"runner": "direct", "workdir": str(tmp_path / "runs")})

    assert result.status == "success"
    assert result.metrics is not None
    assert result.metrics.pce_percent == 21.56
    assert result.metrics.voc_v == 1.1
    assert result.curves is not None
    assert result.curves.jv is not None
    assert result.curves.jv.rows == 3

