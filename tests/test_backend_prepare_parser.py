from __future__ import annotations

import shlex
from pathlib import Path

from solarcell_sim import check_backend, parse_results, prepare_case, run_case, validate_input
from solarcell_sim.api import prepare_case_internal
from solarcell_sim.runners.wine import DirectScapsRunner
from solarcell_sim.storage import read_json

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
    assert "set script_display_mode.fully_suppressed" in script
    assert "set batch_display_mode.suppressed" in script
    assert script.index("set errorhandling.overwritefile") < script.index(
        "load allscapssettingsfile baseline.scaps"
    )
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


def test_runner_reports_partial_when_nonzero_exit_creates_output(baseline_definition: Path, tmp_path: Path) -> None:
    scaps_dir = tmp_path / "scaps"
    scaps_dir.mkdir()
    executable = scaps_dir / "scaps.exe"
    executable.write_text(
        "#!/bin/sh\nmkdir -p results\nprintf 'fake output\\n' > results/pyscaps.out\nexit 6\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    case = sample_case(baseline_definition, tmp_path / "runs", executable=executable)
    prepared = prepare_case_internal(case)

    raw = DirectScapsRunner().run(prepared, prepared.backend_options)

    assert raw.status == "partial"
    assert raw.return_code == 6
    assert raw.result_file == prepared.result_file
    assert raw.diagnostics[0].code == "runner.nonzero_exit"
    assert raw.diagnostics[0].severity == "warning"
    assert "manual does not define" in raw.diagnostics[0].message


def test_runner_reports_partial_when_scaps_error_log_exists(baseline_definition: Path, tmp_path: Path) -> None:
    scaps_dir = tmp_path / "scaps"
    scaps_dir.mkdir()
    executable = scaps_dir / "scaps.exe"
    executable.write_text(
        "#!/bin/sh\nmkdir -p results\nprintf 'fake output\\n' > results/pyscaps.out\n"
        "printf 'non convergence warning\\n' > SCAPSErrorLogFile.log\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    case = sample_case(baseline_definition, tmp_path / "runs", executable=executable)
    prepared = prepare_case_internal(case)

    raw = DirectScapsRunner().run(prepared, prepared.backend_options)

    assert raw.status == "partial"
    assert raw.return_code == 0
    assert raw.error_log_file == prepared.scaps_root / "SCAPSErrorLogFile.log"
    assert any(item.code == "scaps.error_log" for item in raw.diagnostics)


def test_workspace_copy_runtime_is_cleaned_after_parse(baseline_definition: Path, tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "scaps_sample_outputs" / "pyscaps.out"
    scaps_dir = tmp_path / "scaps"
    scaps_dir.mkdir()
    executable = scaps_dir / "scaps.exe"
    executable.write_text(
        "#!/bin/sh\nmkdir -p results\ncp "
        + shlex.quote(str(fixture))
        + " results/pyscaps.out\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    case = sample_case(baseline_definition, tmp_path / "runs", executable=executable)
    case["backendOptions"]["runtimeStrategy"] = "workspace_copy"

    result = run_case(case, cwd=tmp_path)
    run_dir = tmp_path / "runs" / result.run_id
    artifact_paths = {artifact.type: Path(artifact.path) for artifact in result.artifacts}
    manifest = read_json(run_dir / "manifest.json")

    assert result.status == "success"
    assert result.execution is not None
    assert result.execution.raw_status == "success"
    assert result.execution.return_code == 0
    assert result.execution.runtime_cleaned is True
    assert result.output is not None
    assert "script command" in (result.output.result_text or "")
    assert not (run_dir / "runtime").exists()
    assert artifact_paths["definition"].exists()
    assert artifact_paths["script"].exists()
    assert artifact_paths["raw_output"].exists()
    assert artifact_paths["definition"].parent == run_dir / "raw" / "scaps_inputs"
    assert artifact_paths["script"].parent == run_dir / "raw" / "scaps_inputs"
    assert manifest["runtimeCleaned"] is True
    assert manifest["execution"]["runtimeCleaned"] is True
    assert manifest["execution"]["rawStatus"] == "success"
    assert all(
        "/runtime/" not in item["path"]
        for item in manifest["artifacts"]
        if item["type"] in {"definition", "script", "raw_output", "parsed_csv", "parsed_json"}
    )


def test_workspace_copy_archives_scaps_error_log(baseline_definition: Path, tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "scaps_sample_outputs" / "pyscaps.out"
    scaps_dir = tmp_path / "scaps"
    scaps_dir.mkdir()
    executable = scaps_dir / "scaps.exe"
    executable.write_text(
        "#!/bin/sh\nmkdir -p results\ncp "
        + shlex.quote(str(fixture))
        + " results/pyscaps.out\nprintf 'SCAPS convergence message\\n' > SCAPSErrorLogFile.log\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    case = sample_case(baseline_definition, tmp_path / "runs", executable=executable)
    case["backendOptions"]["runtimeStrategy"] = "workspace_copy"

    result = run_case(case, cwd=tmp_path)
    run_dir = tmp_path / "runs" / result.run_id
    log_artifacts = [artifact for artifact in result.artifacts if artifact.type == "log"]

    assert result.status == "partial"
    assert result.execution is not None
    assert result.execution.error_log_file is not None
    assert Path(result.execution.error_log_file).parent == run_dir / "raw" / "scaps_logs"
    assert Path(result.execution.error_log_file).exists()
    assert result.output is not None
    assert "script command" in (result.output.result_text or "")
    assert "SCAPS convergence message" in (result.output.error_log_text or "")
    assert len(log_artifacts) == 1
    assert any(item.code == "scaps.error_log" for item in result.diagnostics)
    assert not (run_dir / "runtime").exists()


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
    assert result.output is not None
    assert "SCAPS output generated by a script" in (result.output.result_text or "")

