from __future__ import annotations

from solarcell_sim.backends.base import SimulatorBackend

_BACKENDS: dict[str, SimulatorBackend] = {}


def register_backend(backend: SimulatorBackend) -> None:
    _BACKENDS[backend.name] = backend


def get_backend(name: str) -> SimulatorBackend:
    if not _BACKENDS:
        from solarcell_sim.backends.scaps import ScapsBackend

        register_backend(ScapsBackend())
    try:
        return _BACKENDS[name]
    except KeyError as exc:
        available = ", ".join(sorted(_BACKENDS)) or "<none>"
        raise KeyError(f"Unknown backend {name!r}. Available backends: {available}") from exc


def list_backends() -> list[str]:
    if not _BACKENDS:
        get_backend("scaps")
    return sorted(_BACKENDS)

