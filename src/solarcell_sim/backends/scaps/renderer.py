from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from solarcell_sim.errors import ConfigurationError
from solarcell_sim.schema import (
    DefinitionArtifact,
    Diagnostic,
    ScriptArtifact,
    SimulationInput,
)
from solarcell_sim.storage import hash_file


def _command(value: Any, scaps_command: str) -> str | None:
    if value is None:
        return None
    return f"{scaps_command} {value}"


class ScapsDefinitionRenderer:
    script_name = "pyscaps.script"
    result_name = "pyscaps.out"

    def render_definition(self, case: SimulationInput, scaps_root: Path) -> DefinitionArtifact:
        source = case.backend_options.definition_source
        if source is None:
            raise ConfigurationError(
                "SCAPS baseline definition is not configured",
                [
                    Diagnostic(
                        severity="error",
                        code="scaps.definition_missing",
                        message="Provide backendOptions.definitionSource.path or SCAPS_DEFINITION_PATH",
                    )
                ],
            )
        if source.type != "baseline_file":
            raise ConfigurationError(
                f"Definition source {source.type!r} is not implemented in P0",
                [
                    Diagnostic(
                        severity="error",
                        code="scaps.definition_source_unsupported",
                        message="P0 supports baseline_file definitions; generated/template sources are reserved for P1",
                    )
                ],
            )
        if source.path is None or not source.path.exists():
            raise ConfigurationError(
                f"SCAPS baseline definition does not exist: {source.path}",
                [
                    Diagnostic(
                        severity="error",
                        code="scaps.definition_not_found",
                        message=f"SCAPS baseline definition does not exist: {source.path}",
                    )
                ],
            )

        definition_dir = scaps_root / "def"
        definition_dir.mkdir(parents=True, exist_ok=True)
        target = definition_dir / source.path.name
        shutil.copy2(source.path, target)
        return DefinitionArtifact(source_type=source.type, path=target, hash=hash_file(target))

    def render_script(self, case: SimulationInput, definition: DefinitionArtifact, scaps_root: Path) -> ScriptArtifact:
        script_dir = scaps_root / "script"
        script_dir.mkdir(parents=True, exist_ok=True)
        result_dir = scaps_root / "results"
        result_dir.mkdir(parents=True, exist_ok=True)

        commands, warnings = self._build_commands(case, definition.path.name)
        script_path = script_dir / self.script_name
        script_path.write_text("\n".join(commands) + "\n", encoding="utf-8")
        return ScriptArtifact(path=script_path, hash=hash_file(script_path), warnings=warnings)

    def _build_commands(self, case: SimulationInput, definition_name: str) -> tuple[list[str], list[Diagnostic]]:
        commands = [
            "//Script file made by PySolarMCP",
            "set quitscript.quitSCAPS",
            f"load allscapssettingsfile {definition_name}",
        ]
        warnings: list[Diagnostic] = []

        for index, layer in enumerate(case.device.layers, start=1):
            material = layer.material
            layer_commands = [
                _command(layer.thickness_nm * 1e-3, f"set layer{index}.thickness"),
                _command(material.bandgap_ev, f"set layer{index}.Eg"),
                _command(material.electron_affinity_ev, f"set layer{index}.chi"),
                _command(material.relative_permittivity, f"set layer{index}.epsilon"),
                _command(material.electron_mobility_cm2_vs, f"set layer{index}.mun"),
                _command(material.hole_mobility_cm2_vs, f"set layer{index}.mup"),
                _command(material.donor_density_cm3, f"set layer{index}.ND"),
                _command(material.acceptor_density_cm3, f"set layer{index}.NA"),
            ]
            commands.extend(command for command in layer_commands if command is not None)
            if material.nc_cm3 is not None or material.nv_cm3 is not None:
                warnings.append(
                    Diagnostic(
                        severity="warning",
                        code="renderer.unmapped_density_of_states",
                        message=f"Layer {index} Nc/Nv fields are validated but not mapped to SCAPS script commands in P0",
                    )
                )
            for defect_index, defect in enumerate(layer.defects, start=1):
                density_command = _command(defect.density_cm3, f"set layer{index}.defect{defect_index}.Ntotal")
                energy_command = _command(defect.energy_ev, f"set layer{index}.defect{defect_index}.Et")
                if density_command:
                    commands.append(density_command)
                if energy_command:
                    commands.append(energy_command)

        if case.device.front_contact.work_function_ev is not None or case.device.back_contact.work_function_ev is not None:
            warnings.append(
                Diagnostic(
                    severity="warning",
                    code="renderer.unmapped_contacts",
                    message="Contact work functions are not mapped to SCAPS script commands in P0",
                )
            )

        scan = case.conditions.voltage_scan
        commands.extend(
            [
                f"action workingpoint.temperature {case.conditions.temperature_k}",
                f"action iv.startv {scan.start_v}",
                f"action iv.stopv {scan.stop_v}",
                f"action iv.increment {scan.step_v}",
                "set errorhandling.overwritefile",
                "calculate singleshot",
                f"save results.iv {self.result_name}",
            ]
        )

        unsupported = sorted(set(case.measurements) - {"JV"})
        if unsupported:
            warnings.append(
                Diagnostic(
                    severity="warning",
                    code="renderer.unsupported_measurements",
                    message=f"P0 only generates JV scripts; unsupported measurements: {', '.join(unsupported)}",
                )
            )
        return commands, warnings

