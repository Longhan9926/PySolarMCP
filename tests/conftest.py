from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def baseline_definition(tmp_path: Path) -> Path:
    path = tmp_path / "baseline.scaps"
    path.write_text("dummy SCAPS definition\n", encoding="utf-8")
    return path


@pytest.fixture
def fake_executable(tmp_path: Path) -> Path:
    path = tmp_path / "scaps.exe"
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def sample_case(baseline_definition: Path, workdir: Path, executable: Path | None = None, runner: str = "direct") -> dict:
    backend_options = {
        "runner": runner,
        "workdir": str(workdir),
        "definitionSource": {"type": "baseline_file", "path": str(baseline_definition)},
    }
    if executable is not None:
        backend_options["executablePath"] = str(executable)
    return {
        "name": "unit-baseline",
        "backend": "scaps",
        "backendOptions": backend_options,
        "device": {
            "architecture": "n-i-p",
            "layers": [
                {
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
                },
                {
                    "name": "PVK",
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
                    "defects": [{"densityCm3": 1e12, "energyEv": 0.3}],
                },
            ],
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

