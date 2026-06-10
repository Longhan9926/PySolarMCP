from __future__ import annotations

from copy import deepcopy
from typing import Any


def _transport_layer() -> dict[str, Any]:
    return {
        "name": "ETL",
        "role": "ETL",
        "thicknessNm": 25,
        "material": {
            "bandgapEv": 2.3,
            "electronAffinityEv": 4.0,
            "relativePermittivity": 9,
            "electronMobilityCm2Vs": 0.01,
            "holeMobilityCm2Vs": 0.001,
            "donorDensityCm3": 1e18,
        },
    }


def _absorber_layer() -> dict[str, Any]:
    return {
        "name": "Perovskite",
        "role": "absorber",
        "thicknessNm": 600,
        "material": {
            "bandgapEv": 1.55,
            "electronAffinityEv": 3.9,
            "relativePermittivity": 25,
            "electronMobilityCm2Vs": 2,
            "holeMobilityCm2Vs": 2,
            "donorDensityCm3": 1e10,
        },
    }


def _hole_layer() -> dict[str, Any]:
    return {
        "name": "HTL",
        "role": "HTL",
        "thicknessNm": 100,
        "material": {
            "bandgapEv": 2.8,
            "electronAffinityEv": 2.2,
            "relativePermittivity": 3,
            "electronMobilityCm2Vs": 0.001,
            "holeMobilityCm2Vs": 0.01,
            "acceptorDensityCm3": 1e18,
        },
    }


def get_baseline_case(architecture: str = "p-i-n", backend: str = "scaps") -> dict[str, Any]:
    """Return a baseline simulation case without backend runtime options."""
    if architecture == "n-i-p":
        layers = [_transport_layer(), _absorber_layer(), _hole_layer()]
        name = "nip-baseline"
    elif architecture == "p-i-n":
        layers = [_hole_layer(), _absorber_layer(), _transport_layer()]
        name = "pin-baseline"
    else:
        raise ValueError("baseline cases support architecture 'p-i-n' or 'n-i-p'")

    return deepcopy(
        {
            "name": name,
            "backend": backend,
            "device": {
                "architecture": architecture,
                "layers": layers,
                "frontContact": {"name": "front"},
                "backContact": {"name": "back"},
            },
            "conditions": {
                "temperatureK": 300,
                "illumination": "AM1.5G",
                "incidentSide": "front",
                "voltageScan": {"startV": 0, "stopV": 1.2, "stepV": 0.05},
            },
            "measurements": ["JV"],
        }
    )
