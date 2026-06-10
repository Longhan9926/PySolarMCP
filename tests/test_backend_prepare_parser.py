from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path

import pytest

from solarcell_sim import check_backend, parse_results, prepare_case, run_case, validate_input
from solarcell_sim.api import prepare_case_internal
from solarcell_sim.runners.wine import DirectScapsRunner, WineScapsRunner
from solarcell_sim.schema import BackendOptions
from solarcell_sim.storage import read_json

from tests.conftest import sample_case


def test_validate_input_accepts_baseline_case(baseline_definition: Path, tmp_path: Path) -> None:
    report = validate_input(sample_case(baseline_definition, tmp_path / "runs"))

    assert report.ok
    assert report.normalized_input is not None


def test_run_case_validation_error_does_not_start_runner(baseline_definition: Path, tmp_path: Path) -> None:
    marker = tmp_path / "runner-started"
    executable = tmp_path / "scaps.exe"
    executable.write_text(f"#!/bin/sh\nprintf started > {shlex.quote(str(marker))}\n", encoding="utf-8")
    executable.chmod(0o755)

    case = sample_case(baseline_definition, tmp_path / "runs", executable=executable)
    case["device"]["layers"][0]["thicknessNm"] = -1

    result = run_case(case, cwd=tmp_path)

    assert result.status == "failed"
    assert result.run_id == "validation-error"
    assert any(item.code == "device.layers[0].thickness" for item in result.diagnostics)
    assert not marker.exists()


def test_run_case_warning_only_input_still_runs(baseline_definition: Path, tmp_path: Path) -> None:
    marker = tmp_path / "runner-started"
    fixture = Path(__file__).parent / "fixtures" / "scaps_sample_outputs" / "pyscaps.out"
    executable = tmp_path / "scaps.exe"
    executable.write_text(
        "#!/bin/sh\nmkdir -p results\nprintf started > "
        + shlex.quote(str(marker))
        + "\ncp "
        + shlex.quote(str(fixture))
        + " results/pyscaps.out\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    case = sample_case(baseline_definition, tmp_path / "runs", executable=executable)
    case["conditions"]["temperatureK"] = 50
    case["device"]["layers"][0]["material"]["electronMobilityCm2Vs"] = 1e6

    result = run_case(case, cwd=tmp_path)

    assert marker.exists()
    assert result.status == "success"
    assert any(item.code == "conditions.temperature.extreme" for item in result.diagnostics)
    assert any(item.code == "device.layers[0].material.electronMobilityCm2Vs.large" for item in result.diagnostics)


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


def test_prepare_case_selects_pin_template_by_architecture(
    baseline_definition: Path,
    fake_executable: Path,
    template_definitions: dict[str, Path],
    tmp_path: Path,
) -> None:
    case = sample_case(baseline_definition, tmp_path / "runs", executable=fake_executable)
    case["device"]["architecture"] = "p-i-n"
    case["device"]["layers"][0]["name"] = "HTL"
    case["device"]["layers"][0]["role"] = "HTL"
    case["backendOptions"]["definitionSource"] = {
        "type": "template",
        "templatePaths": {key: str(path) for key, path in template_definitions.items()},
    }

    prepared = prepare_case_internal(case)
    script = prepared.script.path.read_text(encoding="utf-8")

    assert prepared.definition.source_type == "template"
    assert prepared.definition.path.name == "template_pin.scaps"
    assert prepared.definition.path.read_text(encoding="utf-8") == "p-i-n SCAPS template\n"
    assert "load allscapssettingsfile template_pin.scaps" in script


def test_prepare_case_selects_nip_template_by_architecture(
    baseline_definition: Path,
    fake_executable: Path,
    template_definitions: dict[str, Path],
    tmp_path: Path,
) -> None:
    case = sample_case(baseline_definition, tmp_path / "runs", executable=fake_executable)
    case["backendOptions"]["definitionSource"] = {
        "type": "template",
        "templatePaths": {key: str(path) for key, path in template_definitions.items()},
    }

    prepared = prepare_case_internal(case)
    script = prepared.script.path.read_text(encoding="utf-8")

    assert prepared.definition.source_type == "template"
    assert prepared.definition.path.name == "template_nip.scaps"
    assert prepared.definition.path.read_text(encoding="utf-8") == "n-i-p SCAPS template\n"
    assert "load allscapssettingsfile template_nip.scaps" in script


def test_prepare_case_rejects_template_architecture_mismatch(
    baseline_definition: Path,
    fake_executable: Path,
    template_definitions: dict[str, Path],
    tmp_path: Path,
) -> None:
    case = sample_case(baseline_definition, tmp_path / "runs", executable=fake_executable)
    case["backendOptions"]["definitionSource"] = {
        "type": "template",
        "templateName": "p-i-n",
        "templatePaths": {key: str(path) for key, path in template_definitions.items()},
    }

    result = prepare_case(case)

    assert result.status == "config_required"
    assert any(item.code == "scaps.template_architecture_mismatch" for item in result.diagnostics)


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


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group behavior is tested on Linux")
def test_runner_timeout_kills_child_processes(baseline_definition: Path, tmp_path: Path) -> None:
    marker = tmp_path / "child-survived"
    scaps_dir = tmp_path / "scaps"
    scaps_dir.mkdir()
    executable = scaps_dir / "scaps.exe"
    executable.write_text(
        "#!/bin/sh\n"
        f"(sleep 2; printf survived > {shlex.quote(str(marker))}) &\n"
        "wait\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    case = sample_case(baseline_definition, tmp_path / "runs", executable=executable)
    case["backendOptions"]["timeoutSeconds"] = 1
    prepared = prepare_case_internal(case)

    raw = DirectScapsRunner().run(prepared, prepared.backend_options)
    time.sleep(2.5)

    assert raw.status == "failed"
    assert any(item.code == "runner.timeout" for item in raw.diagnostics)
    assert not marker.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell fixture is tested on Linux")
def test_runner_timeout_reports_display_failure(baseline_definition: Path, tmp_path: Path) -> None:
    scaps_dir = tmp_path / "scaps"
    scaps_dir.mkdir()
    executable = scaps_dir / "scaps.exe"
    executable.write_text(
        "#!/bin/sh\n"
        "printf 'Application tried to create a window, but no driver could be loaded. "
        "Make sure that your X server is running and that DISPLAY is set correctly.\\n' >&2\n"
        "sleep 2\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    case = sample_case(baseline_definition, tmp_path / "runs", executable=executable)
    case["backendOptions"]["timeoutSeconds"] = 1
    prepared = prepare_case_internal(case)

    raw = DirectScapsRunner().run(prepared, prepared.backend_options)

    assert raw.status == "failed"
    assert [item.code for item in raw.diagnostics][:2] == ["runner.display_unavailable", "runner.timeout"]
    assert "X server" in raw.diagnostics[0].message


def test_wine_runner_reports_xvfb_preflight_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_which(name: str) -> str:
        return f"/usr/bin/{name}"

    def fake_run(*args, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args[0], 1, "", "xvfb-run: error: Xvfb failed to start")

    monkeypatch.setattr("solarcell_sim.runners.wine.shutil.which", fake_which)
    monkeypatch.setattr("solarcell_sim.runners.wine.subprocess.run", fake_run)

    diagnostics = WineScapsRunner().check_runner(
        BackendOptions(runner="wine", use_xvfb=True, wine_bin="wine", xvfb_bin="xvfb-run")
    )

    assert diagnostics[0].code == "runner.display_unavailable"
    assert "Xvfb preflight failed" in diagnostics[0].message


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


def test_check_backend_accepts_template_source(
    fake_executable: Path,
    template_definitions: dict[str, Path],
    tmp_path: Path,
) -> None:
    status = check_backend(
        backend_options={
            "runner": "direct",
            "executablePath": str(fake_executable),
            "workdir": str(tmp_path / "runs"),
            "definitionSource": {
                "type": "template",
                "templatePaths": {key: str(path) for key, path in template_definitions.items()},
            },
        },
        cwd=tmp_path,
    )

    assert status.status == "available"
    assert status.diagnostics == []


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
