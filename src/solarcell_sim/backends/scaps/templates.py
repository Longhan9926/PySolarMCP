from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from solarcell_sim.errors import ConfigurationError
from solarcell_sim.schema import DefinitionSource, Diagnostic

SUPPORTED_TEMPLATE_ARCHITECTURES = ("p-i-n", "n-i-p")
AUTO_TEMPLATE_NAMES = {"", "auto", "architecture", "by-architecture"}

_TEMPLATE_ALIASES = {
    "p-i-n-baseline": "p-i-n",
    "baseline-pin": "p-i-n",
    "baseline-p-i-n": "p-i-n",
    "n-i-p-baseline": "n-i-p",
    "baseline-nip": "n-i-p",
    "baseline-n-i-p": "n-i-p",
}


@dataclass(frozen=True)
class TemplateSelection:
    architecture: str
    source_path: Path

    @property
    def definition_name(self) -> str:
        return f"template_{self.architecture.replace('-', '')}.scaps"


def normalize_template_name(name: str) -> str | None:
    normalized = name.strip().lower().replace("_", "-")
    compact = normalized.replace("-", "")
    if compact == "pin":
        return "p-i-n"
    if compact == "nip":
        return "n-i-p"
    return _TEMPLATE_ALIASES.get(normalized)


def select_template_architecture(source: DefinitionSource, architecture: str) -> str:
    requested = (source.template_name or "").strip()
    if requested.lower().replace("_", "-") in AUTO_TEMPLATE_NAMES:
        requested = architecture

    selected = normalize_template_name(requested)
    if selected is None:
        raise ConfigurationError(
            f"Unsupported SCAPS template architecture: {requested!r}",
            [
                Diagnostic(
                    severity="error",
                    code="scaps.template_unknown",
                    message=(
                        "SCAPS templates support architecture p-i-n and n-i-p. "
                        "Use templateName 'auto' or omit templateName to follow device.architecture."
                    ),
                )
            ],
        )

    if architecture != "custom" and selected != architecture:
        raise ConfigurationError(
            f"SCAPS template {selected!r} does not match device architecture {architecture!r}",
            [
                Diagnostic(
                    severity="error",
                    code="scaps.template_architecture_mismatch",
                    message=(
                        f"Template {selected!r} does not match device.architecture {architecture!r}; "
                        "omit templateName or set it to 'auto' to select by architecture."
                    ),
                )
            ],
        )
    return selected


def _template_paths_by_architecture(source: DefinitionSource) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for raw_name, path in source.template_paths.items():
        normalized = normalize_template_name(raw_name)
        if normalized is not None:
            paths[normalized] = path
    return paths


def _candidate_paths(source: DefinitionSource, architecture: str) -> list[Path]:
    paths = _template_paths_by_architecture(source)
    candidates: list[Path] = []
    if architecture in paths:
        candidates.append(paths[architecture])
    if source.path is not None:
        if source.path.is_dir():
            candidates.extend(
                [
                    source.path / architecture / "baseline.scaps",
                    source.path / architecture.replace("-", "") / "baseline.scaps",
                ]
            )
        else:
            candidates.append(source.path)
    return candidates


def resolve_template_definition(source: DefinitionSource, architecture: str) -> TemplateSelection:
    selected = select_template_architecture(source, architecture)
    candidates = _candidate_paths(source, selected)
    if not candidates:
        raise ConfigurationError(
            "SCAPS template definition is not configured",
            [
                Diagnostic(
                    severity="error",
                    code="scaps.template_missing",
                    message=(
                        f"Configure a template path for architecture {selected!r} with "
                        "backendOptions.definitionSource.templatePaths, SCAPS_TEMPLATE_PIN_PATH, "
                        "or SCAPS_TEMPLATE_NIP_PATH."
                    ),
                )
            ],
        )

    for path in candidates:
        if path.exists():
            return TemplateSelection(architecture=selected, source_path=path)

    searched = ", ".join(str(path) for path in candidates)
    raise ConfigurationError(
        f"SCAPS template definition does not exist for {selected}: {searched}",
        [
            Diagnostic(
                severity="error",
                code="scaps.template_not_found",
                message=f"SCAPS template definition does not exist for {selected}: {searched}",
            )
        ],
    )


def validate_template_source(source: DefinitionSource) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    requested = (source.template_name or "").strip().lower().replace("_", "-")

    if requested not in AUTO_TEMPLATE_NAMES:
        try:
            selected = normalize_template_name(source.template_name or "")
            if selected is None:
                raise ConfigurationError(
                    f"Unsupported SCAPS template architecture: {source.template_name!r}",
                    [
                        Diagnostic(
                            severity="error",
                            code="scaps.template_unknown",
                            message="SCAPS templates support architecture p-i-n and n-i-p.",
                        )
                    ],
                )
            resolve_template_definition(source, selected)
        except ConfigurationError as exc:
            diagnostics.extend(exc.diagnostics)
        return diagnostics

    candidates = []
    paths = _template_paths_by_architecture(source)
    for architecture in SUPPORTED_TEMPLATE_ARCHITECTURES:
        candidates.extend(_candidate_paths(source, architecture))
    if not candidates and not paths:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="scaps.template_missing",
                message=(
                    "SCAPS template source is selected but no template paths are configured. "
                    "Provide templatePaths or SCAPS_TEMPLATE_PIN_PATH/SCAPS_TEMPLATE_NIP_PATH."
                ),
            )
        )
        return diagnostics

    if source.path is not None:
        if not source.path.exists():
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="scaps.template_not_found",
                    message=f"SCAPS template path does not exist: {source.path}",
                )
            )
        elif source.path.is_dir() and not any(path.exists() for path in candidates):
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="scaps.template_not_found",
                    message=f"SCAPS template directory contains no p-i-n or n-i-p baseline.scaps files: {source.path}",
                )
            )

    for raw_path in paths.values():
        if not raw_path.exists():
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="scaps.template_not_found",
                    message=f"SCAPS template definition does not exist: {raw_path}",
                )
            )
    return diagnostics
