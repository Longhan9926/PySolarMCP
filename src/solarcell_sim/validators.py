from __future__ import annotations

import math

from solarcell_sim.schema import Diagnostic, SimulationInput, ValidationReport


def _warning(code: str, message: str) -> Diagnostic:
    return Diagnostic(severity="warning", code=code, message=message)


def _error(code: str, message: str) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message)


def _is_finite(value: float | int | None) -> bool:
    return value is None or math.isfinite(float(value))


def _warn_if_outside(
    warnings: list[Diagnostic],
    code: str,
    value: float | int | None,
    lower: float,
    upper: float,
    message: str,
) -> None:
    if value is not None and not lower <= float(value) <= upper:
        warnings.append(_warning(code, message))


def validate_simulation_input(case: SimulationInput) -> ValidationReport:
    errors: list[Diagnostic] = []
    warnings: list[Diagnostic] = []

    layers = case.device.layers
    if not layers:
        errors.append(_error("device.layers.empty", "device.layers must contain at least one layer"))
    elif not any(layer.role == "absorber" for layer in layers):
        warnings.append(_warning("device.layers.absorber_missing", "device.layers has no absorber layer"))

    if len(layers) > 8:
        warnings.append(_warning("device.layers.many", "device has more than 8 layers; SCAPS runs may be slow or unstable"))

    roles = [layer.role for layer in layers]
    if case.device.architecture == "n-i-p":
        try:
            absorber_index = roles.index("absorber")
        except ValueError:
            absorber_index = -1
        if absorber_index >= 0 and ("HTL" in roles[:absorber_index] or "ETL" in roles[absorber_index + 1 :]):
            warnings.append(_warning("device.architecture.layer_order", "n-i-p architecture usually has ETL before absorber and HTL after absorber"))
    elif case.device.architecture == "p-i-n":
        try:
            absorber_index = roles.index("absorber")
        except ValueError:
            absorber_index = -1
        if absorber_index >= 0 and ("ETL" in roles[:absorber_index] or "HTL" in roles[absorber_index + 1 :]):
            warnings.append(_warning("device.architecture.layer_order", "p-i-n architecture usually has HTL before absorber and ETL after absorber"))

    if "JV" not in case.measurements:
        warnings.append(_warning("measurements.jv_missing", "P0 parser and runner primarily support JV output"))

    if not _is_finite(case.conditions.temperature_k):
        errors.append(_error("conditions.temperature", "temperatureK must be finite"))
    elif case.conditions.temperature_k <= 0:
        errors.append(_error("conditions.temperature", "temperatureK must be positive"))
    elif not 250 <= case.conditions.temperature_k <= 400:
        warnings.append(_warning("conditions.temperature.extreme", "temperatureK is outside the typical 250-400 K range"))

    scan = case.conditions.voltage_scan
    if not all(_is_finite(value) for value in (scan.start_v, scan.stop_v, scan.step_v)):
        errors.append(_error("voltage_scan.finite", "voltage scan values must be finite"))
    else:
        steps = abs((scan.stop_v - scan.start_v) / scan.step_v)
        if steps > 2000:
            warnings.append(_warning("voltage_scan.large", "voltage scan has more than 2000 steps and may run slowly"))
        if abs(scan.start_v) > 5 or abs(scan.stop_v) > 5:
            warnings.append(_warning("voltage_scan.range", "voltage scan exceeds +/-5 V, which is unusual for solar-cell JV simulation"))

    total_thickness_nm = 0.0
    for index, layer in enumerate(layers, start=1):
        prefix = f"device.layers[{index - 1}]"
        if not _is_finite(layer.thickness_nm):
            errors.append(_error(f"{prefix}.thickness", "layer thickness must be finite"))
        elif layer.thickness_nm <= 0:
            errors.append(_error(f"{prefix}.thickness", "layer thickness must be positive"))
        else:
            total_thickness_nm += layer.thickness_nm
            if layer.thickness_nm > 10000:
                warnings.append(_warning(f"{prefix}.thickness.large", "layer thickness is unusually large for SCAPS"))
            elif layer.thickness_nm < 1:
                warnings.append(_warning(f"{prefix}.thickness.small", "layer thickness is below 1 nm"))

        material = layer.material
        for attr_name, value in (
            ("bandgapEv", material.bandgap_ev),
            ("electronAffinityEv", material.electron_affinity_ev),
            ("relativePermittivity", material.relative_permittivity),
            ("ncCm3", material.nc_cm3),
            ("nvCm3", material.nv_cm3),
            ("electronMobilityCm2Vs", material.electron_mobility_cm2_vs),
            ("holeMobilityCm2Vs", material.hole_mobility_cm2_vs),
            ("donorDensityCm3", material.donor_density_cm3),
            ("acceptorDensityCm3", material.acceptor_density_cm3),
        ):
            if not _is_finite(value):
                errors.append(_error(f"{prefix}.material.{attr_name}", f"{attr_name} must be finite"))

        if not 0 < material.bandgap_ev < 10:
            errors.append(_error(f"{prefix}.material.bandgap", "bandgapEv must be between 0 and 10 eV"))
        if not 0 < material.relative_permittivity < 100:
            errors.append(_error(f"{prefix}.material.relativePermittivity", "relativePermittivity must be between 0 and 100"))

        _warn_if_outside(
            warnings,
            f"{prefix}.material.electronAffinity",
            material.electron_affinity_ev,
            0,
            10,
            "electronAffinityEv is outside the typical 0-10 eV range",
        )
        for attr_name, value in (
            ("electronMobilityCm2Vs", material.electron_mobility_cm2_vs),
            ("holeMobilityCm2Vs", material.hole_mobility_cm2_vs),
            ("donorDensityCm3", material.donor_density_cm3),
            ("acceptorDensityCm3", material.acceptor_density_cm3),
        ):
            if value is not None and value < 0:
                errors.append(_error(f"{prefix}.material.{attr_name}", f"{attr_name} cannot be negative"))

        for attr_name, value in (
            ("electronMobilityCm2Vs", material.electron_mobility_cm2_vs),
            ("holeMobilityCm2Vs", material.hole_mobility_cm2_vs),
        ):
            if value is not None and value > 1e4:
                warnings.append(_warning(f"{prefix}.material.{attr_name}.large", f"{attr_name} is unusually large"))

        for attr_name, value in (
            ("donorDensityCm3", material.donor_density_cm3),
            ("acceptorDensityCm3", material.acceptor_density_cm3),
        ):
            if value is not None and value > 1e22:
                warnings.append(_warning(f"{prefix}.material.{attr_name}.large", f"{attr_name} is unusually large"))

        if (material.donor_density_cm3 or 0) > 1e18 and (material.acceptor_density_cm3 or 0) > 1e18:
            warnings.append(_warning(f"{prefix}.material.compensated_doping", "both donor and acceptor densities are high"))

        for attr_name, value in (("ncCm3", material.nc_cm3), ("nvCm3", material.nv_cm3)):
            if value is not None and value <= 0:
                warnings.append(_warning(f"{prefix}.material.{attr_name}", f"{attr_name} should be positive when supplied"))

        for defect_index, defect in enumerate(layer.defects, start=1):
            defect_prefix = f"{prefix}.defects[{defect_index - 1}]"
            if not _is_finite(defect.density_cm3):
                errors.append(_error(f"{defect_prefix}.density", "defect density must be finite"))
            elif defect.density_cm3 is not None and defect.density_cm3 < 0:
                errors.append(_error(f"{defect_prefix}.density", "defect density cannot be negative"))
            elif defect.density_cm3 is not None and defect.density_cm3 > 1e20:
                warnings.append(_warning(f"{defect_prefix}.density.large", "defect density is unusually large"))

            if not _is_finite(defect.energy_ev):
                errors.append(_error(f"{defect_prefix}.energy", "defect energy must be finite"))
            elif defect.energy_ev is not None and not -10 < defect.energy_ev < 10:
                warnings.append(_warning(f"{defect_prefix}.energy", "defect energy is outside a typical range"))

    if total_thickness_nm > 20000:
        warnings.append(_warning("device.thickness.total_large", "total device thickness exceeds 20 micrometers"))

    for contact_name, contact in (
        ("frontContact", case.device.front_contact),
        ("backContact", case.device.back_contact),
    ):
        if not _is_finite(contact.work_function_ev):
            errors.append(_error(f"device.{contact_name}.workFunction", "work function must be finite"))
        else:
            _warn_if_outside(
                warnings,
                f"device.{contact_name}.workFunction",
                contact.work_function_ev,
                0,
                10,
                "contact work function is outside the typical 0-10 eV range",
            )
        if not _is_finite(contact.surface_recombination_velocity_cm_s):
            errors.append(_error(f"device.{contact_name}.surfaceRecombinationVelocity", "surface recombination velocity must be finite"))
        elif contact.surface_recombination_velocity_cm_s is not None and contact.surface_recombination_velocity_cm_s < 0:
            warnings.append(_warning(f"device.{contact_name}.surfaceRecombinationVelocity", "surface recombination velocity should not be negative"))

    return ValidationReport(
        errors=errors,
        warnings=warnings,
        normalized_input=case.model_dump(mode="json", by_alias=True),
    )
