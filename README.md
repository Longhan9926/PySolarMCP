# PySolarMCP

PySolarMCP wraps solar-cell device simulation behind two surfaces:

- `solarcell_sim`: a Python package for scripts, notebooks, optimizers, and tests.
- `solarcell_sim_mcp`: a thin MCP adapter that exposes the same core API to agents.

P0 focuses on SCAPS through a baseline `.scaps` definition plus a generated script. The
runner and artifacts are intentionally designed so a later release can generate `.scaps`
definition files directly without changing the public API.

## Python usage

```python
from solarcell_sim import prepare_case, run_case

result = prepare_case({
    "name": "nip-baseline",
    "backendOptions": {
        "definitionSource": {
            "type": "baseline_file",
            "path": "./external/definitions/baseline.scaps"
        }
    },
    "device": {"architecture": "n-i-p", "layers": [], "frontContact": {}, "backContact": {}},
    "conditions": {
        "temperatureK": 300,
        "illumination": "AM1.5G",
        "incidentSide": "front",
        "voltageScan": {"startV": 0, "stopV": 1.2, "stepV": 0.05}
    },
    "measurements": ["JV"]
})
print(result.run_id)
```

## SCAPS inputs

SCAPS is not distributed with this project. Provide it through configuration or Docker
volumes:

- `SCAPS_EXECUTABLE_PATH`: path to `scaps.exe`
- `SCAPS_DEFINITION_PATH`: path to a baseline `.scaps` file
- `SCAPS_WORKDIR`: persistent run directory
- `WINE_BIN`: Wine executable, default `wine`
- `WINEPREFIX`: persistent Wine prefix

The P0 backend copies or links the SCAPS runtime into a per-run workspace, writes the
generated script under `script/`, and reads `results/pyscaps.out`.

Copy `.env.example` to `.env` for local configuration:

```bash
cp .env.example .env
```

For a shared machine install, place SCAPS under `/opt/scaps` and keep `/opt/scaps`
read-only for normal users. Use per-user or per-project writable directories for
`SCAPS_WORKDIR` and `WINEPREFIX`.

`docker compose` reads `.env` automatically for variable substitution. The host path
variables such as `SCAPS_HOST_DIR` are used for volume mounts; the Docker-specific
variables such as `SCAPS_DOCKER_EXECUTABLE_PATH` must stay as container paths.

## Runner smoke test

Use the smoke script to verify local SCAPS/Wine runner configuration:

```bash
uv run python scripts/smoke_scaps_runner.py --prepare-only
uv run python scripts/smoke_scaps_runner.py --timeout-seconds 60
```

The script reads `.env`, prepares a case from `examples/nip_baseline.json`, invokes the
configured runner, and prints raw stdout/stderr plus parsed diagnostics.

## Docker MCP server

Build the image:

```bash
docker build -t solarcell-sim-mcp:latest .
```

Run over MCP stdio:

```json
{
  "mcpServers": {
    "solarcell-sim": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-v", "/path/to/scaps:/scaps:ro",
        "-v", "/path/to/definitions:/definitions:ro",
        "-v", "/path/to/runs:/runs",
        "-v", "/path/to/wineprefix:/wineprefix",
        "-e", "SCAPS_EXECUTABLE_PATH=/scaps/scaps.exe",
        "-e", "SCAPS_DEFINITION_PATH=/definitions/baseline.scaps",
        "-e", "SCAPS_WORKDIR=/runs",
        "-e", "WINEPREFIX=/wineprefix",
        "solarcell-sim-mcp:latest"
      ]
    }
  }
}
```

With Docker Compose, configure `.env` and run:

```bash
docker compose build
docker compose run --rm solarcell-sim-mcp --check
```

The image includes Python, Wine, and Xvfb. It does not include SCAPS, baseline definition
files, run artifacts, or a Wine prefix.
