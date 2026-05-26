from __future__ import annotations

import shutil
from pathlib import Path
from typing import Literal

from solarcell_sim.backends.scaps.parser import parse_scaps_iv_file
from solarcell_sim.backends.scaps.renderer import ScapsDefinitionRenderer
from solarcell_sim.config import load_backend_options
from solarcell_sim.diagnostics import result_quality_diagnostics
from solarcell_sim.errors import ConfigurationError, ValidationError
from solarcell_sim.runners.wine import DirectScapsRunner, WineScapsRunner
from solarcell_sim.runners.windows_native import NativeWindowsScapsRunner
from solarcell_sim.schema import (
    ArtifactRef,
    BackendOptions,
    BackendStatus,
    Diagnostic,
    EnvironmentInfo,
    ExecutionInfo,
    PreparedCase,
    RawRunResult,
    SimulationCurves,
    SimulationOutput,
    SimulationInput,
    SimulationResult,
    ValidationReport,
)
from solarcell_sim.storage import create_run_id, hash_file, write_json
from solarcell_sim.validators import validate_simulation_input


def _read_text_if_present(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    return path.read_text(encoding="ISO-8859-1", errors="replace")


class ScapsBackend:
    name = "scaps"
    version = None

    def __init__(self) -> None:
        self.renderer = ScapsDefinitionRenderer()

    def check_available(self, config: BackendOptions) -> BackendStatus:
        diagnostics: list[Diagnostic] = []
        if config.executable_path is None:
            diagnostics.append(
                Diagnostic(severity="error", code="scaps.executable_missing", message="SCAPS executable path is not configured")
            )
        elif not config.executable_path.exists():
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="scaps.executable_not_found",
                    message=f"SCAPS executable does not exist: {config.executable_path}",
                )
            )

        source = config.definition_source
        if source is None:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="scaps.definition_missing",
                    message="SCAPS baseline definition is not configured",
                )
            )
        elif source.type != "baseline_file":
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="scaps.definition_source_unsupported",
                    message=f"Definition source {source.type!r} is reserved for a future renderer",
                )
            )
        elif source.path is None or not source.path.exists():
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="scaps.definition_not_found",
                    message=f"SCAPS baseline definition does not exist: {source.path}",
                )
            )

        if config.workdir is None:
            diagnostics.append(
                Diagnostic(severity="error", code="scaps.workdir_missing", message="SCAPS workdir is not configured")
            )
        else:
            try:
                config.workdir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                diagnostics.append(
                    Diagnostic(severity="error", code="scaps.workdir_unwritable", message=str(exc))
                )

        diagnostics.extend(self._runner_for(config).check_runner(config))
        status = "available" if not diagnostics else "config_required"
        return BackendStatus(
            backend=self.name,
            status=status,
            runner=config.runner,
            diagnostics=diagnostics,
            executable_path=str(config.executable_path) if config.executable_path else None,
            definition_path=str(source.path) if source and source.path else None,
            workdir=str(config.workdir) if config.workdir else None,
            wine_bin=config.wine_bin,
            wine_prefix=str(config.wine_prefix) if config.wine_prefix else None,
        )

    def validate_input(self, case: SimulationInput) -> ValidationReport:
        return validate_simulation_input(case)

    def prepare_case(self, case: SimulationInput, config: BackendOptions) -> PreparedCase:
        report = self.validate_input(case)
        if report.errors:
            raise ValidationError("Simulation input validation failed", report.errors)
        if config.workdir is None:
            raise ConfigurationError("SCAPS workdir is not configured")

        case = case.model_copy(update={"backend_options": config})
        run_id = create_run_id(case.name, case.model_dump(mode="json", by_alias=True))
        run_dir = config.workdir / run_id
        scaps_root = run_dir / "runtime" / "scaps_root"
        for directory in (
            run_dir / "input",
            run_dir / "raw",
            run_dir / "parsed",
            scaps_root / "def",
            scaps_root / "script",
            scaps_root / "results",
        ):
            directory.mkdir(parents=True, exist_ok=True)

        write_json(run_dir / "input" / "request.json", case.model_dump(mode="json", by_alias=True))
        write_json(run_dir / "input" / "normalized_input.json", case.model_dump(mode="json", by_alias=True))
        write_json(run_dir / "input" / "backend_config.json", config.model_dump(mode="json", by_alias=True))

        definition = self.renderer.render_definition(case, scaps_root)
        script = self.renderer.render_script(case, definition, scaps_root)
        result_file = scaps_root / "results" / self.renderer.result_name
        manifest_path = run_dir / "manifest.json"
        artifacts = [
            ArtifactRef(type="input", path=str(run_dir / "input" / "request.json")),
            ArtifactRef(type="definition", path=str(definition.path)),
            ArtifactRef(type="script", path=str(script.path)),
            ArtifactRef(type="manifest", path=str(manifest_path)),
        ]
        diagnostics = report.warnings + script.warnings
        manifest = {
            "runId": run_id,
            "backend": self.name,
            "runner": config.runner,
            "workdir": str(run_dir),
            "scapsRoot": str(scaps_root),
            "definition": definition.model_dump(mode="json", by_alias=True),
            "script": script.model_dump(mode="json", by_alias=True),
            "inputHash": hash_file(run_dir / "input" / "normalized_input.json"),
            "artifacts": [item.model_dump(mode="json", by_alias=True) for item in artifacts],
            "diagnostics": [item.model_dump(mode="json", by_alias=True) for item in diagnostics],
        }
        write_json(manifest_path, manifest)
        return PreparedCase(
            run_id=run_id,
            workdir=run_dir,
            scaps_root=scaps_root,
            definition=definition,
            script=script,
            result_file=result_file,
            manifest_path=manifest_path,
            backend_options=config,
            artifacts=artifacts,
            diagnostics=diagnostics,
        )

    def run_case(self, prepared: PreparedCase, config: BackendOptions) -> RawRunResult:
        status = self.check_available(config)
        if status.status != "available":
            return RawRunResult(
                run_id=prepared.run_id,
                status="config_required",
                result_file=None,
                diagnostics=status.diagnostics,
            )
        return self._runner_for(config).run(prepared, config)

    def parse_results(self, raw: RawRunResult, prepared: PreparedCase) -> SimulationResult:
        diagnostics = list(prepared.diagnostics) + list(raw.diagnostics)
        artifacts = self._archive_prepared_artifacts(prepared, diagnostics)
        metrics = None
        curves = SimulationCurves()
        raw_output_path: Path | None = None

        result_file = raw.result_file or prepared.result_file
        if result_file.exists():
            raw_dir = prepared.workdir / "raw" / "scaps_outputs"
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_copy = raw_dir / result_file.name
            if raw_copy.resolve() != result_file.resolve():
                shutil.copy2(result_file, raw_copy)
            raw_output_path = raw_copy
            artifacts.append(ArtifactRef(type="raw_output", path=str(raw_copy)))
            metrics, curves, parse_diagnostics = parse_scaps_iv_file(raw_copy, prepared.workdir / "parsed")
            diagnostics.extend(parse_diagnostics)
            diagnostics.extend(result_quality_diagnostics(metrics))
            if curves.jv is not None:
                artifacts.append(ArtifactRef(type="parsed_csv", path=curves.jv.path))
            artifacts.append(ArtifactRef(type="parsed_json", path=str(prepared.workdir / "parsed" / "metrics.json")))

        error_log_path = self._archive_error_log(raw, prepared, artifacts, diagnostics)

        if raw.status == "success" and metrics is not None:
            status = "success"
        elif raw.status == "config_required":
            status = "config_required"
        elif metrics is not None:
            status = "partial"
        else:
            status = "failed"

        runtime_cleaned = False
        if prepared.backend_options.runtime_strategy == "workspace_copy":
            runtime_cleaned = self._cleanup_runtime(prepared, diagnostics)

        output = SimulationOutput(
            stdout=raw.stdout,
            stderr=raw.stderr,
            result_text=_read_text_if_present(raw_output_path),
            error_log_text=_read_text_if_present(error_log_path),
        )
        execution = ExecutionInfo(
            raw_status=raw.status,
            return_code=raw.return_code,
            result_file=str(raw_output_path) if raw_output_path else None,
            error_log_file=str(error_log_path) if error_log_path else None,
            runtime_cleaned=runtime_cleaned,
        )

        self._update_manifest(prepared, status, artifacts, diagnostics, execution)

        return SimulationResult(
            run_id=prepared.run_id,
            backend=self.name,
            backend_version=self.version,
            runner=prepared.backend_options.runner,
            status=status,
            metrics=metrics,
            curves=curves,
            diagnostics=diagnostics,
            artifacts=artifacts,
            environment=EnvironmentInfo(
                executable_path=str(prepared.backend_options.executable_path) if prepared.backend_options.executable_path else None,
                wine_bin=prepared.backend_options.wine_bin,
                wine_prefix=str(prepared.backend_options.wine_prefix) if prepared.backend_options.wine_prefix else None,
                runner=prepared.backend_options.runner,
            ),
            execution=execution,
            output=output,
        )

    def parse_existing(self, output_path: Path, config: BackendOptions) -> SimulationResult:
        parsed_dir = output_path.parent / "parsed"
        metrics, curves, diagnostics = parse_scaps_iv_file(output_path, parsed_dir)
        diagnostics.extend(result_quality_diagnostics(metrics))
        return SimulationResult(
            run_id=output_path.parent.name,
            backend=self.name,
            runner=config.runner,
            status="success" if metrics is not None else "failed",
            metrics=metrics,
            curves=curves,
            diagnostics=diagnostics,
            artifacts=[
                ArtifactRef(type="raw_output", path=str(output_path)),
                ArtifactRef(type="parsed_json", path=str(parsed_dir / "metrics.json")),
            ],
            execution=ExecutionInfo(
                raw_status="success" if metrics is not None else "failed",
                result_file=str(output_path),
            ),
            output=SimulationOutput(result_text=_read_text_if_present(output_path)),
        )

    def _archive_prepared_artifacts(self, prepared: PreparedCase, diagnostics: list[Diagnostic]) -> list[ArtifactRef]:
        if prepared.backend_options.runtime_strategy != "workspace_copy":
            return list(prepared.artifacts)

        archived: list[ArtifactRef] = []
        archive_dir = prepared.workdir / "raw" / "scaps_inputs"
        for artifact in prepared.artifacts:
            if artifact.type == "definition":
                archived.append(
                    self._copy_runtime_artifact(prepared.definition.path, archive_dir, "definition", diagnostics)
                )
            elif artifact.type == "script":
                archived.append(
                    self._copy_runtime_artifact(prepared.script.path, archive_dir, "script", diagnostics)
                )
            else:
                archived.append(artifact)
        return archived

    def _copy_runtime_artifact(
        self,
        source: Path,
        destination_dir: Path,
        artifact_type: Literal["definition", "script"],
        diagnostics: list[Diagnostic],
    ) -> ArtifactRef:
        destination = destination_dir / source.name
        try:
            destination_dir.mkdir(parents=True, exist_ok=True)
            if source.exists() and destination.resolve() != source.resolve():
                shutil.copy2(source, destination)
                return ArtifactRef(type=artifact_type, path=str(destination))
        except OSError as exc:
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="runtime.archive_failed",
                    message=f"Failed to archive {artifact_type} artifact {source}: {exc}",
                )
            )
        return ArtifactRef(type=artifact_type, path=str(source))

    def _archive_error_log(
        self,
        raw: RawRunResult,
        prepared: PreparedCase,
        artifacts: list[ArtifactRef],
        diagnostics: list[Diagnostic],
    ) -> Path | None:
        if raw.error_log_file is None or not raw.error_log_file.exists():
            return None

        destination_dir = prepared.workdir / "raw" / "scaps_logs"
        destination = destination_dir / raw.error_log_file.name
        try:
            destination_dir.mkdir(parents=True, exist_ok=True)
            if destination.resolve() != raw.error_log_file.resolve():
                shutil.copy2(raw.error_log_file, destination)
            artifacts.append(ArtifactRef(type="log", path=str(destination)))
            return destination
        except OSError as exc:
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="runtime.archive_failed",
                    message=f"Failed to archive SCAPS error log {raw.error_log_file}: {exc}",
                )
            )
            return raw.error_log_file

    def _cleanup_runtime(self, prepared: PreparedCase, diagnostics: list[Diagnostic]) -> bool:
        runtime_dir = prepared.workdir / "runtime"
        if not runtime_dir.exists():
            return True
        try:
            shutil.rmtree(runtime_dir)
            return True
        except OSError as exc:
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="runtime.cleanup_failed",
                    message=f"Failed to clean runtime directory {runtime_dir}: {exc}",
                )
            )
            return False

    def _update_manifest(
        self,
        prepared: PreparedCase,
        status: str,
        artifacts: list[ArtifactRef],
        diagnostics: list[Diagnostic],
        execution: ExecutionInfo,
    ) -> None:
        try:
            manifest = {
                "runId": prepared.run_id,
                "backend": self.name,
                "runner": prepared.backend_options.runner,
                "status": status,
                "workdir": str(prepared.workdir),
                "runtimeStrategy": prepared.backend_options.runtime_strategy,
                "runtimeCleaned": execution.runtime_cleaned,
                "execution": execution.model_dump(mode="json", by_alias=True),
                "inputHash": hash_file(prepared.workdir / "input" / "normalized_input.json"),
                "artifacts": [item.model_dump(mode="json", by_alias=True) for item in artifacts],
                "diagnostics": [item.model_dump(mode="json", by_alias=True) for item in diagnostics],
            }
            write_json(prepared.manifest_path, manifest)
        except OSError as exc:
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="manifest.update_failed",
                    message=f"Failed to update manifest after parsing: {exc}",
                )
            )

    def _runner_for(self, config: BackendOptions):
        if config.runner == "direct":
            return DirectScapsRunner()
        if config.runner == "windows_native":
            return NativeWindowsScapsRunner()
        return WineScapsRunner()
