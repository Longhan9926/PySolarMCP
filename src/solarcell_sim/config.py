from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from solarcell_sim.schema import BackendOptions, DefinitionSource


def _default_workdir() -> Path:
    return Path.home() / ".local" / "share" / "solarcell-sim" / "runs"


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        elif value is not None:
            merged[key] = value
    return merged


def _env_config() -> dict[str, Any]:
    config: dict[str, Any] = {}
    backend = os.getenv("SOLARCELL_SIM_BACKEND")
    if backend:
        config["backend"] = {"default": backend}

    scaps: dict[str, Any] = {}
    if value := os.getenv("SCAPS_EXECUTABLE_PATH"):
        scaps["executable_path"] = value
    if value := os.getenv("SCAPS_WORKDIR"):
        scaps["workdir"] = value
    if value := os.getenv("SCAPS_DEFINITION_PATH"):
        scaps["definition_source"] = {"type": "baseline_file", "path": value}
    if value := os.getenv("SCAPS_RUNTIME_STRATEGY"):
        scaps["runtime_strategy"] = value

    wine: dict[str, Any] = {}
    if value := os.getenv("WINE_BIN"):
        wine["bin"] = value
    if value := os.getenv("WINEPREFIX"):
        wine["prefix"] = value
    if value := os.getenv("SOLARCELL_SIM_XVFB"):
        wine["use_xvfb"] = value.lower() in {"1", "true", "yes", "on"}
    if wine:
        scaps["wine"] = wine
    if scaps:
        config["backends"] = {"scaps": scaps}
    return config


def _options_from_config(config: dict[str, Any], backend: str) -> dict[str, Any]:
    backend_config = config.get("backends", {}).get(backend, {})
    wine = backend_config.get("wine", {})
    options = {
        "runner": backend_config.get("runner"),
        "executable_path": backend_config.get("executable_path"),
        "workdir": backend_config.get("workdir"),
        "definition_source": backend_config.get("definition_source"),
        "runtime_strategy": backend_config.get("runtime_strategy"),
        "wine_bin": wine.get("bin"),
        "wine_prefix": wine.get("prefix"),
        "use_xvfb": wine.get("use_xvfb"),
    }
    return {key: value for key, value in options.items() if value is not None}


def load_backend_options(
    backend: str = "scaps",
    overrides: BackendOptions | dict[str, Any] | None = None,
    cwd: Path | None = None,
) -> BackendOptions:
    cwd = cwd or Path.cwd()
    config: dict[str, Any] = {
        "backend": {"default": "scaps"},
        "backends": {
            "scaps": {
                "runner": "wine",
                "workdir": str(_default_workdir()),
                "wine": {"bin": "wine"},
                "runtime_strategy": "workspace_link",
            }
        },
    }

    config = _deep_merge(config, _env_config())
    config = _deep_merge(config, _read_toml(Path.home() / ".config" / "solarcell-sim" / "config.toml"))
    config = _deep_merge(config, _read_toml(cwd / ".solarcell-sim.toml"))

    option_data = _options_from_config(config, backend)

    if overrides is not None:
        if isinstance(overrides, BackendOptions):
            override_data = overrides.model_dump(exclude_unset=True)
        else:
            override_data = dict(overrides)
        option_data = _deep_merge(option_data, override_data)

    if isinstance(option_data.get("definition_source"), dict):
        option_data["definition_source"] = DefinitionSource.model_validate(option_data["definition_source"])

    return BackendOptions.model_validate(option_data)

