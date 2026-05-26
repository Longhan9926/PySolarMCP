from __future__ import annotations

from solarcell_sim.schema import Diagnostic, SimulationInput, ValidationReport


def _warning(code: str, message: str) -> Diagnostic:
    return Diagnostic(severity="warning", code=code, message=message)


def _error(code: str, message: str) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message)


def validate_simulation_input(case: SimulationInput) -> ValidationReport:
    errors: list[Diagnostic] = []
    warnings: list[Diagnostic] = []

    if not case.device.layers:
        errors.append(_error("device.layers.empty", "device.layers must contain at least one layer"))

    if "JV" not in case.measurements:
        warnings.append(_warning("measurements.jv_missing", "P0 parser and runner primarily support JV output"))

    scan = case.conditions.voltage_scan
    steps = abs((scan.stop_v - scan.start_v) / scan.step_v)
    if steps > 2000:
        warnings.append(_warning("voltage_scan.large", "voltage scan has more than 2000 steps"))

    for index, layer in enumerate(case.device.layers, start=1):
        prefix = f"device.layers[{index - 1}]"
        if layer.thickness_nm <= 0:
            errors.append(_error(f"{prefix}.thickness", "layer thickness must be positive"))
        elif layer.thickness_nm > 10000:
            warnings.append(_warning(f"{prefix}.thickness.large", "layer thickness is unusually large for SCAPS"))

        material = layer.material
        if not 0 < material.bandgap_ev < 10:
            errors.append(_error(f"{prefix}.material.bandgap", "bandgapEv must be between 0 and 10 eV"))
        if not 0 < material.relative_permittivity < 100:
            errors.append(_error(f"{prefix}.material.relativePermittivity", "relativePermittivity must be between 0 and 100"))

        for attr_name, value in (
            ("electronMobilityCm2Vs", material.electron_mobility_cm2_vs),
            ("holeMobilityCm2Vs", material.hole_mobility_cm2_vs),
            ("donorDensityCm3", material.donor_density_cm3),
            ("acceptorDensityCm3", material.acceptor_density_cm3),
        ):
            if value is not None and value < 0:
                errors.append(_error(f"{prefix}.material.{attr_name}", f"{attr_name} cannot be negative"))

        for defect_index, defect in enumerate(layer.defects, start=1):
            if defect.density_cm3 is not None and defect.density_cm3 < 0:
                errors.append(_error(f"{prefix}.defects[{defect_index - 1}].density", "defect density cannot be negative"))
            if defect.energy_ev is not None and not -10 < defect.energy_ev < 10:
                warnings.append(_warning(f"{prefix}.defects[{defect_index - 1}].energy", "defect energy is outside a typical range"))

    return ValidationReport(
        errors=errors,
        warnings=warnings,
        normalized_input=case.model_dump(mode="json", by_alias=True),
    )

