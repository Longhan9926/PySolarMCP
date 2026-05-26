from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Mapping

from solarcell_sim.schema import BackendOptions, DefinitionSource


def _default_workdir() -> Path:
    return Path.home() / ".local" / "share" / "solarcell-sim" / "runs"


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()

        key, separator, value = line.partition("=")
        if not separator:
            continue

        key = key.strip()
        if not key:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value

    return values


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        elif value is not None:
            merged[key] = value
    return merged


def _env_config(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    environ = os.environ if environ is None else environ
    config: dict[str, Any] = {}
    backend = environ.get("SOLARCELL_SIM_BACKEND")
    if backend:
        config["backend"] = {"default": backend}

    scaps: dict[str, Any] = {}
    if value := environ.get("SCAPS_EXECUTABLE_PATH"):
        scaps["executable_path"] = value
    if value := environ.get("SCAPS_WORKDIR"):
        scaps["workdir"] = value
    if value := environ.get("SCAPS_DEFINITION_PATH"):
        scaps["definition_source"] = {"type": "baseline_file", "path": value}
    if value := environ.get("SCAPS_RUNTIME_STRATEGY"):
        scaps["runtime_strategy"] = value

    wine: dict[str, Any] = {}
    if value := environ.get("WINE_BIN"):
        wine["bin"] = value
    if value := environ.get("WINEPREFIX"):
        wine["prefix"] = value
    if value := environ.get("WINEARCH"):
        wine["arch"] = value
    if value := environ.get("SOLARCELL_SIM_XVFB"):
        wine["use_xvfb"] = value.lower() in {"1", "true", "yes", "on"}
    if wine:
        scaps["wine"] = wine
    if scaps:
        config["backends"] = {"scaps": scaps}
    return config


def _resolve_path(path: Path | None, cwd: Path) -> Path | None:
    if path is None or path.is_absolute():
        return path
    return cwd / path


def _resolve_option_paths(options: BackendOptions, cwd: Path) -> BackendOptions:
    options.executable_path = _resolve_path(options.executable_path, cwd)
    options.workdir = _resolve_path(options.workdir, cwd)
    options.wine_prefix = _resolve_path(options.wine_prefix, cwd)
    if options.definition_source is not None:
        options.definition_source.path = _resolve_path(options.definition_source.path, cwd)
    return options


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
        "wine_arch": wine.get("arch"),
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

    config = _deep_merge(config, _env_config(_read_dotenv(cwd / ".env")))
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

    return _resolve_option_paths(BackendOptions.model_validate(option_data), cwd)

