from __future__ import annotations

from copy import deepcopy
from typing import Any

from solarcell_sim.schema import Diagnostic, SimulationInput, SimulationMaterial


SCAPS_CARD_TO_SIMULATION_MATERIAL = {
    "bandgapEv": "bandgapEv",
    "electronAffinityEv": "electronAffinityEv",
    "permittivityRelative": "relativePermittivity",
    "mobilityElectronCm2Vs": "electronMobilityCm2Vs",
    "mobilityHoleCm2Vs": "holeMobilityCm2Vs",
    "NcCm3": "ncCm3",
    "NvCm3": "nvCm3",
    "defectDensityCm3": None,
    "relativeElectronMass": None,
    "relativeHoleMass": None,
}


def _field_value(field: Any) -> Any:
    if isinstance(field, dict) and "value" in field:
        return field["value"]
    return field


def build_layer_material_from_card(
    card: dict[str, Any],
    base_material: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert a MatContractServer ScapsMaterialCard to PySolarMCP material fields."""
    material = dict(base_material or {})
    fields = card.get("scapsFields") or card.get("scaps_fields") or {}
    for card_field, material_field in SCAPS_CARD_TO_SIMULATION_MATERIAL.items():
        if material_field is None or card_field not in fields:
            continue
        material[material_field] = _field_value(fields[card_field])
    return material


def apply_scaps_material_card(
    case: dict[str, Any] | SimulationInput,
    card: dict[str, Any],
    *,
    layer_name: str | None = None,
    layer_index: int | None = None,
    role: str | None = None,
    preserve_existing: bool = True,
) -> dict[str, Any]:
    """Apply a SCAPS material card to one device layer and return a normalized case."""
    raw_case = case.model_dump(mode="json", by_alias=True) if isinstance(case, SimulationInput) else deepcopy(case)
    layers = raw_case.get("device", {}).get("layers", [])
    index, diagnostics = _resolve_layer_index(
        layers,
        layer_name=layer_name,
        layer_index=layer_index,
        role=role,
    )
    if index is None:
        return {
            "status": "failed",
            "case": raw_case,
            "diagnostics": [item.model_dump(mode="json", by_alias=True) for item in diagnostics],
        }

    existing = layers[index].get("material", {}) if preserve_existing else {}
    layers[index]["material"] = build_layer_material_from_card(card, existing)

    try:
        normalized = SimulationInput.model_validate(raw_case)
    except Exception as exc:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="material_card.case_validation_failed",
                message=str(exc),
            )
        )
        return {
            "status": "failed",
            "case": raw_case,
            "diagnostics": [item.model_dump(mode="json", by_alias=True) for item in diagnostics],
        }

    return {
        "status": "success",
        "case": normalized.model_dump(mode="json", by_alias=True),
        "diagnostics": [item.model_dump(mode="json", by_alias=True) for item in diagnostics],
    }


def _resolve_layer_index(
    layers: list[dict[str, Any]],
    *,
    layer_name: str | None,
    layer_index: int | None,
    role: str | None,
) -> tuple[int | None, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    selectors = [value is not None for value in (layer_name, layer_index, role)]
    if sum(selectors) != 1:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="material_card.layer_selector_required",
                message="Provide exactly one of layerName, layerIndex, or role.",
            )
        )
        return None, diagnostics

    if layer_index is not None:
        if layer_index < 0 or layer_index >= len(layers):
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="material_card.layer_index_out_of_range",
                    message=f"layerIndex {layer_index} is outside the layer list.",
                )
            )
            return None, diagnostics
        return layer_index, diagnostics

    key = "name" if layer_name is not None else "role"
    value = layer_name if layer_name is not None else role
    matches = [index for index, layer in enumerate(layers) if layer.get(key) == value]
    if not matches:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="material_card.layer_not_found",
                message=f"No layer matched {key}={value}.",
            )
        )
        return None, diagnostics
    if len(matches) > 1:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="material_card.layer_selector_ambiguous",
                message=f"Multiple layers matched {key}={value}; use layerIndex instead.",
            )
        )
        return None, diagnostics
    return matches[0], diagnostics
