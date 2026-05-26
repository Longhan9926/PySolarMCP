# PySolarMCP

PySolarMCP wraps solar-cell device simulation behind two surfaces:

- `solarcell_sim`: a Python package for scripts, notebooks, optimizers, and tests.
- `solarcell_sim_mcp`: a thin MCP adapter that exposes the same core API to agents.

P0 focuses on SCAPS through a baseline `.scaps` definition plus a generated script. The
runner and artifacts are intentionally designed so a later release can generate `.scaps`
definition files directly without changing the public API.

## Python usage

Use the package directly from scripts, notebooks, optimizers, or tests. The runtime
configuration is loaded from `.env`, environment variables, and optional config files.

```python
from pathlib import Path

from solarcell_sim import run_case
from solarcell_sim.storage import read_json

case = read_json(Path("examples/nip_baseline.json"))
case.pop("backendOptions", None)  # use .env / project config

result = run_case(case)
print(result.status)
print(result.metrics)
print(result.execution)
```

SCAPS/Wine can return a non-zero process code after writing a valid output file. In that
case `result.status` is `partial`, parsed metrics are still returned when available, and
the raw process details remain available under `result.execution`. The generated SCAPS
output text is available as `result.output.result_text`.

## Local SCAPS and Wine setup

SCAPS is not distributed with this project. Install or copy it on the host machine, then
point PySolarMCP at that installation. The recommended shared-machine layout is:

```bash
/opt/scaps/Scaps3309/scaps3310.exe
/opt/scaps/Scaps3309/Scapsdll.dll
/opt/scaps/Scaps3309/def/baseline.scaps
/opt/scaps/ScapsInstallation/bin/dp/Scaps3310.msi
```

Keep `/opt/scaps` read-only for normal users. Keep writable state such as `runs/` and
`wineprefix/` per user or per project. Do not share one writable Wine prefix between
multiple users unless you also control concurrent access and permissions.

Create a local config file:

```bash
cp .env.example .env
```

For a host-side local run, the important values are:

```env
SCAPS_EXECUTABLE_PATH=/opt/scaps/Scaps3309/scaps3310.exe
SCAPS_DEFINITION_PATH=/opt/scaps/Scaps3309/def/baseline.scaps
SCAPS_WORKDIR=./runs
SCAPS_RUNTIME_STRATEGY=workspace_copy
WINE_BIN=wine
WINEPREFIX=./wineprefix
WINEARCH=win32
SOLARCELL_SIM_XVFB=1
```

Use a 32-bit Wine prefix. `WINEARCH=win32` only matters when a prefix is first created;
it will not convert an existing 64-bit prefix. Initialize the prefix and install the SCAPS
MSI into it:

```bash
uv run python scripts/setup_scaps_wine.py --installer /opt/scaps/ScapsInstallation/bin/dp/Scaps3310.msi
```

Passing `/opt/scaps/ScapsInstallation/setup.exe` is also supported; the helper looks for
`bin/dp/*.msi` next to it first. The direct MSI path is preferred because the SCAPS
`setup.exe` bootstrapper can hang under Wine. The MSI installs runtime dependencies such
as the NI LabWindows/CVI runtime (`cvirte.dll`).

## Local runner verification

Run a prepare-only check first. This verifies config resolution, SCAPS definition copying,
and script generation without launching Wine:

```bash
uv run python scripts/smoke_scaps_runner.py --prepare-only
```

Then run SCAPS:

```bash
uv run python scripts/smoke_scaps_runner.py --timeout-seconds 90
```

The smoke script reads `.env`, prepares `examples/nip_baseline.json`, runs the configured
backend, and prints raw stdout/stderr, parsed diagnostics, execution metadata, metrics,
and artifact paths. Generated scripts follow the SCAPS manual's scripting guidance:
messages are directed to `SCAPSErrorLogFile.log` with `set errorhandling.overwritefile`;
if that log is written, it is archived under `raw/scaps_logs/` and surfaced as a
diagnostic.

For `SCAPS_RUNTIME_STRATEGY=workspace_copy`, each run copies the SCAPS runtime into a
per-run workspace, then removes `runtime/` after parsing. Long-lived artifacts remain in:

```text
runs/<run-id>/input/
runs/<run-id>/raw/scaps_inputs/
runs/<run-id>/raw/scaps_outputs/
runs/<run-id>/raw/scaps_logs/
runs/<run-id>/parsed/
runs/<run-id>/manifest.json
```

Some SCAPS/Wine combinations return a non-zero process code after writing a valid output
file. The SCAPS manual does not define these process return codes, so parseable output is
returned in `output.resultText` while the process code remains available as
`execution.returnCode`. The smoke script exits 0 for parseable partial results by
default. Add `--strict-exit-code` to make partial results fail the smoke command.

## Configuration reference

Host-side local runtime variables:

- `SCAPS_EXECUTABLE_PATH`: host path to `scaps3310.exe` or another SCAPS executable.
- `SCAPS_DEFINITION_PATH`: host path to a baseline `.scaps` file.
- `SCAPS_WORKDIR`: persistent run directory.
- `SCAPS_RUNTIME_STRATEGY`: `workspace_copy`, `workspace_link`, or `in_place`;
  `workspace_copy` is recommended for reproducible runs and Docker.
- `WINE_BIN`: Wine executable, default `wine`.
- `WINEPREFIX`: writable Wine prefix containing SCAPS runtime dependencies.
- `WINEARCH`: normally `win32` for SCAPS.
- `SOLARCELL_SIM_XVFB`: set to `1` to wrap Wine in `xvfb-run` on headless machines.

Docker Compose also reads `.env`. Host path variables such as `SCAPS_HOST_DIR` are used
for volume mounts; Docker-specific variables such as `SCAPS_DOCKER_EXECUTABLE_PATH` must
stay as container paths.

## Docker remote MCP server

The Docker image now runs the MCP server as an always-on Streamable HTTP service by
default. The stdio transport is still available for local process-based MCP clients, but
remote deployments should use HTTP.

### 1. Prepare SCAPS assets on the server

Follow the local SCAPS/Wine setup above on the machine that will run Docker. At minimum:

```bash
cp .env.example .env
uv run python scripts/setup_scaps_wine.py --installer /opt/scaps/ScapsInstallation/bin/dp/Scaps3310.msi
uv run python scripts/smoke_scaps_runner.py --timeout-seconds 90
```

Then confirm the Docker-specific `.env` values match the host layout and the container
mount points:

```env
SCAPS_HOST_DIR=/opt/scaps/Scaps3309
SCAPS_DEFINITIONS_HOST_DIR=/opt/scaps/Scaps3309/def
SCAPS_RUNS_HOST_DIR=./runs
SCAPS_WINEPREFIX_HOST_DIR=./wineprefix

SCAPS_DOCKER_EXECUTABLE_PATH=/scaps/scaps3310.exe
SCAPS_DOCKER_DEFINITION_PATH=/definitions/baseline.scaps
SCAPS_DOCKER_WORKDIR=/runs
WINE_DOCKER_PREFIX=/wineprefix
WINE_DOCKER_ARCH=win32
SOLARCELL_SIM_DOCKER_XVFB=1

DOCKER_UID=1000
DOCKER_GID=1000
DOCKER_HOME=/tmp

MCP_HOST_PORT=31335
MCP_PORT=31335
MCP_PATH=/mcp
```

The container mounts `SCAPS_WINEPREFIX_HOST_DIR` at `/wineprefix`, so SCAPS can find
installed runtime DLLs such as `cvirte.dll`. Wine requires the prefix to be owned by the
user running Wine. Set `DOCKER_UID` and `DOCKER_GID` in `.env` to the host user that owns
`runs/` and `wineprefix/`:

```bash
id -u
id -g
mkdir -p runs wineprefix
sudo chown -R "$(id -u):$(id -g)" runs wineprefix
```

### 2. Build and start the HTTP MCP server

```bash
docker compose build
docker compose config
docker compose up -d solarcell-sim-mcp
```

The service listens on:

```text
http://<server-host>:31335/mcp
```

You can validate construction without starting the long-running HTTP server:

```bash
docker compose run --rm solarcell-sim-mcp --check --transport streamable-http --host 0.0.0.0 --port 31335 --path /mcp
```

Check logs after starting the service:

```bash
docker compose logs -f solarcell-sim-mcp
```

To stop it:

```bash
docker compose down
```

### 3. Configure a local MCP client to use the remote server

Use a URL-based remote MCP configuration. The exact file location depends on your MCP
client, but the server entry should look like this:

```json
{
  "mcpServers": {
    "pysolar-mcp": {
      "url": "http://SERVER_HOST_OR_IP:31335/mcp"
    }
  }
}
```

Replace `SERVER_HOST_OR_IP` with the machine running Docker. If the server is not on a
trusted private network, put it behind SSH tunneling, a VPN, or a reverse proxy with TLS
and authentication before exposing it. The current app-level server does not add its own
authentication layer.

For local testing against the same machine:

```json
{
  "mcpServers": {
    "pysolar-mcp": {
      "url": "http://127.0.0.1:31335/mcp"
    }
  }
}
```

MCP clients should treat backend runtime configuration as server-owned. Do not send
`backendOptions` in MCP requests. Select the simulator with the tool's `backend`
argument, for example `scaps`, and send only the physical simulation case:

```json
{
  "backend": "scaps",
  "case": {
    "name": "nip-baseline-jv",
    "device": {
      "architecture": "n-i-p",
      "layers": [
        {
          "name": "absorber",
          "role": "absorber",
          "thicknessNm": 600,
          "material": {
            "bandgapEv": 1.55,
            "electronAffinityEv": 3.9,
            "relativePermittivity": 25
          }
        }
      ]
    },
    "conditions": {
      "temperatureK": 300,
      "illumination": "AM1.5G",
      "incidentSide": "front",
      "voltageScan": {"startV": 0, "stopV": 1.2, "stepV": 0.05}
    },
    "measurements": ["JV"]
  }
}
```

The remote server loads SCAPS executable paths, baseline definitions, Wine prefix,
workdir, and runtime strategy from its `.env`, Docker environment, or server config.

### 4. Optional stdio mode

For clients that still need process-based stdio, override the Docker command:

```json
{
  "mcpServers": {
    "pysolar-mcp-stdio": {
      "command": "docker",
      "args": [
        "compose",
        "run",
        "--rm",
        "-i",
        "solarcell-sim-mcp",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

For remote deployment, prefer the HTTP URL configuration above instead of stdio.

### 5. Operational notes

- `SCAPS_RUNTIME_STRATEGY=workspace_copy` is recommended for remote runs; generated
  runtime directories are cleaned after parsing while raw inputs, raw outputs, parsed
  CSV/JSON, and manifests are kept.
- A SCAPS/Wine process may return a non-zero process code after writing a valid output
  file. The API returns parseable output as `partial`, with `execution.returnCode` and
  diagnostics preserved.
- If you see `cvirte.dll` missing, the mounted Wine prefix has not had the SCAPS MSI
  installed into it, or the wrong `SCAPS_WINEPREFIX_HOST_DIR` is mounted.
- If Wine reports `/wineprefix` is not owned by you, set `DOCKER_UID` and `DOCKER_GID`
  in `.env` to the host owner of `SCAPS_WINEPREFIX_HOST_DIR`, then recreate the service.
- If `xvfb-run` reports `xauth command not found`, rebuild the Docker image after
  updating this repository; the image must include both `xvfb` and `xauth`.
- If port `31335` is already in use, change `MCP_HOST_PORT` in `.env` and restart with
  `docker compose up -d`. The client URL must use the host port.
