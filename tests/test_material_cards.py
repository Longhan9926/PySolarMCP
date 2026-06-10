from __future__ import annotations

from copy import deepcopy

from solarcell_sim import api


def _card() -> dict:
    return {
        "schemaVersion": "1.0.0",
        "material": {"formula": "CdTe"},
        "scapsFields": {
            "bandgapEv": {"value": 1.52, "unit": "eV", "confidence": "medium"},
            "electronAffinityEv": {"value": 4.28, "unit": "eV", "confidence": "medium"},
            "permittivityRelative": {"value": 10.2, "unit": "dimensionless", "confidence": "medium"},
            "mobilityElectronCm2Vs": {"value": 120.0, "unit": "cm^2/V/s", "confidence": "medium"},
            "mobilityHoleCm2Vs": {"value": 80.0, "unit": "cm^2/V/s", "confidence": "medium"},
            "NcCm3": {"value": 2.2e18, "unit": "cm^-3", "confidence": "medium"},
            "NvCm3": {"value": 1.8e19, "unit": "cm^-3", "confidence": "medium"},
        },
    }


def test_build_layer_material_from_scaps_card() -> None:
    material = api.build_layer_material_from_scaps_card(
        _card(),
        base_material={"donorDensityCm3": 1e10},
    )

    assert material["bandgapEv"] == 1.52
    assert material["electronAffinityEv"] == 4.28
    assert material["relativePermittivity"] == 10.2
    assert material["electronMobilityCm2Vs"] == 120.0
    assert material["holeMobilityCm2Vs"] == 80.0
    assert material["ncCm3"] == 2.2e18
    assert material["nvCm3"] == 1.8e19
    assert material["donorDensityCm3"] == 1e10


def test_apply_scaps_material_card_to_absorber(sample_case_dict: dict) -> None:
    case = deepcopy(sample_case_dict)

    result = api.apply_scaps_material_card_to_case(case, _card(), role="absorber")

    assert result["status"] == "success"
    absorber = result["case"]["device"]["layers"][1]["material"]
    assert absorber["bandgapEv"] == 1.52
    assert absorber["relativePermittivity"] == 10.2
    assert absorber["donorDensityCm3"] == 1e10


def test_apply_scaps_material_card_requires_single_selector(sample_case_dict: dict) -> None:
    result = api.apply_scaps_material_card_to_case(
        sample_case_dict,
        _card(),
        layer_name="Perovskite",
        role="absorber",
    )

    assert result["status"] == "failed"
    assert result["diagnostics"][0]["code"] == "material_card.layer_selector_required"
