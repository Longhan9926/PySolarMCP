# SCAPS MCP Wrapper 设计

> 当前默认 backend：`scaps`。架构上不要把 MCP、Python package 和 SCAPS 执行器耦合死，后续需要能接入其他太阳电池模拟器 backend。

## 目标

把太阳电池器件模拟能力封装成两层：

- **Python package**：提供可直接 `import` 的模拟器调用接口，供脚本、notebook、优化程序和其他系统使用。
- **MCP server**：作为 Python package 的轻量协议适配层，让 PerovskiteAgent/Codex/Claude 等 agent 能调用同一套能力。

第一版默认使用 **SCAPS backend**。SCAPS 是 Windows-based 软件，不随 wrapper 分发；用户需要自行下载/放置 SCAPS 可执行文件，并通过配置指定路径。在 macOS/Linux 上优先通过 Wine 运行 SCAPS。

核心定位：

```text
Agent / Python user / notebook / optimizer
  -> Python package API
  -> backend registry
  -> default backend: SCAPS
  -> input rendering + simulation execution + result parsing
  -> metrics + curves + diagnostics + artifacts
```

这个 wrapper 不应该试图让 SCAPS 变成材料生成器或工艺模拟器。它只负责“给定器件参数下的器件级快速评估”。如果未来接入其他 backend，也应遵守同一个抽象：输入是器件/材料/条件，输出是器件级模拟结果和诊断信息。

## 总体架构

建议采用“Python package 优先，MCP adapter 其次”的分层设计。MCP server 只做协议和工具暴露，真正的业务能力放在 Python package 里。

```text
Python users / notebooks / optimizers
  -> import solarcell_sim
  -> solarcell_sim.run_case / run_sweep / parse_results

PerovskiteAgent / Codex / Claude
  -> MCP tools
  -> solarcell-sim-mcp
  -> same solarcell_sim Python API

solarcell_sim Python package
  -> canonical schema + units + validators
  -> backend registry
  -> SimulatorBackend interface
  -> default backend: ScapsBackend
  -> future backends: wxAMPS / SETFOS / custom Python / surrogate model
  -> runner: WineScapsRunner / NativeWindowsScapsRunner
  -> artifacts: input files / raw outputs / parsed CSV-JSON / logs
```

## 模块划分

| 模块 | 职责 | 输入 | 输出 | 备注 |
|---|---|---|---|---|
| `solarcell_sim.api` | Python package 对外入口 | Python dict/model | `SimulationResult` | 非 MCP 用户也直接调用这一层。 |
| `solarcell_sim.schema` | 定义通用器件、材料、缺陷、接触、扫描任务 | user/agent JSON | typed model | 不绑定 SCAPS，尽量是 simulator-neutral schema。 |
| `solarcell_sim.units` | 单位归一化和范围检查 | `nm`、`um`、`cm^-3`、`eV` 等 | canonical units | 防止 agent 或用户填错单位。 |
| `solarcell_sim.validators` | 通用物理 sanity check | typed model | warnings/errors | 检查带隙、迁移率、缺陷密度、厚度、能带排列。 |
| `solarcell_sim.backends` | backend 抽象和注册表 | canonical input | backend-specific case | 默认注册 `scaps`，未来注册其他太阳电池模拟器。 |
| `solarcell_sim.backends.scaps` | SCAPS backend 实现 | canonical input + SCAPS config | `.def`、script、raw outputs | 处理 SCAPS 文件格式、Wine/Windows 执行和 SCAPS 输出解析。 |
| `solarcell_sim.runners` | 执行环境抽象 | workdir + command/script | raw outputs + logs | 只保留 Wine 和本机 Windows 两种 runner。 |
| `solarcell_sim.parsers` | 通用/后端专用输出解析 | raw files | tables + metrics | 后端专用 parser 输出统一结果 schema。 |
| `solarcell_sim.diagnostics` | 结果质量检查和瓶颈归因 | parsed result | warnings + explanation | 给 agent 用，不只返回数字。 |
| `solarcell_sim.storage` | 管理 run_id、输入、输出和日志 | run artifacts | reproducible run folder | 每次运行必须可追溯。 |
| `solarcell_sim_mcp.server` | MCP adapter | MCP tool request | JSON response + artifact URI | 尽量薄，只调用 Python package API。 |

## Backend 抽象

后端接口应该面向“太阳电池模拟器”，而不是只面向 SCAPS。SCAPS 是第一版默认后端。

```python
class SimulatorBackend(Protocol):
    name: str
    version: str | None

    def check_available(self, config: BackendConfig) -> BackendStatus: ...
    def validate_input(self, case: SimulationInput) -> ValidationReport: ...
    def prepare_case(self, case: SimulationInput, workdir: Path) -> PreparedCase: ...
    def run_case(self, prepared: PreparedCase, config: BackendConfig) -> RawRunResult: ...
    def parse_results(self, raw: RawRunResult) -> SimulationResult: ...
```

第一版只实现：

```text
backend = "scaps"
backend_impl = ScapsBackend
runner = WineScapsRunner | NativeWindowsScapsRunner
```

未来可扩展：

| Backend | 可能用途 | 接入方式 |
|---|---|---|
| `scaps` | 1D 薄膜/钙钛矿太阳电池器件仿真 | 默认 backend；Wine/Windows 执行。 |
| `wxamps` | 另一类 1D 太阳电池器件仿真 | 实现同样的 backend interface。 |
| `setfos` | 光电耦合/有机与钙钛矿器件建模 | 通过商业软件 CLI/API 或文件接口接入。 |
| `custom_python` | 组内自研模型或代理模型 | 直接 Python function backend。 |
| `surrogate_model` | ML 代理模型快速预测 | 不运行物理模拟器，返回预测和不确定性。 |

## 推荐目录结构

```text
solarcell-sim/
  pyproject.toml
  README.md
  src/
    solarcell_sim/
      __init__.py
      api.py
      config.py
      schema.py
      units.py
      validators.py
      diagnostics.py
      storage.py
      backends/
        __init__.py
        base.py
        registry.py
        scaps/
          __init__.py
          backend.py
          config.py
          renderer.py
          parser.py
          templates/
            baseline_nip/
              device.def.template
              run.script.template
      runners/
        __init__.py
        base.py
        wine.py
        windows_native.py
      examples/
        nip_baseline.json
        sweep_thickness_defect.json
      tests/
        test_schema.py
        test_units.py
        test_backend_registry.py
        test_scaps_renderer.py
        test_scaps_parser.py
        fixtures/
          scaps_sample_outputs/
    solarcell_sim_mcp/
      server.py
      tools/
        run_case.py
        run_sweep.py
        validate_input.py
        check_backend.py
        parse_results.py
        get_artifact.py
```

Python package 是主产品形态，MCP server 是可选入口。这样即使不作为 MCP，也可以：

```python
from solarcell_sim import run_case

result = run_case(case, backend="scaps")
print(result.metrics.pce_percent)
```

如果现有 agent runtime 更偏 TypeScript，也可以让 MCP server 用 TypeScript，但它仍应通过 Python CLI 或 Python package 调用同一套 core 能力，避免出现两套实现。

## MCP Tools 设计

MCP tool 名称建议使用通用前缀 `solarcell_*`，默认参数 `backend="scaps"`。第一版如果为了便于记忆，也可以保留 `scaps_*` 作为 alias，但内部应统一调用 `solarcell_sim` Python package。

### 1. `solarcell_check_backend`

检查 backend 是否可用，尤其是 SCAPS 可执行文件和 Wine 环境是否配置正确。

| 字段 | 说明 |
|---|---|
| 输入 | `backend`，可选 `backend_config` |
| 输出 | backend status、resolved executable path、runner type、errors、warnings |
| 用途 | agent 或用户在运行前确认环境。SCAPS backend 不可用时，不应进入仿真。 |

### 2. `solarcell_validate_input`

只验证输入，不运行具体 backend。

| 字段 | 说明 |
|---|---|
| 输入 | `SimulationInput`，默认 `backend="scaps"` |
| 输出 | normalized input、errors、warnings、missing fields |
| 用途 | agent 在正式运行前检查单位、参数范围和字段完整性。 |

### 3. `solarcell_prepare_case`

生成可复现的 backend case 文件夹。默认生成 SCAPS case。

| 字段 | 说明 |
|---|---|
| 输入 | `SimulationInput`，`backend="scaps"`，可选 backend config |
| 输出 | `run_id`、workdir、生成的 backend 输入文件路径、warnings |
| 用途 | 适合第一阶段。即使暂不运行，也能产出可复现的 backend 输入包；正式 runner 只支持 Wine 或本机 Windows。 |

### 4. `solarcell_run_case`

运行单个仿真 case。

| 字段 | 说明 |
|---|---|
| 输入 | `run_id` 或完整 `SimulationInput`，`backend`，`runner`，`timeout` |
| 输出 | status、backend、metrics、curves、diagnostics、artifact refs |
| 用途 | agent 的主要调用入口。 |

### 5. `solarcell_run_sweep`

运行参数扫描。

| 字段 | 说明 |
|---|---|
| 输入 | baseline input、backend、sweep variables、parallelism、stop policy |
| 输出 | sweep table、best candidates、failed cases、diagnostics |
| 用途 | 厚度、缺陷密度、迁移率、电子亲和能、界面态等参数优化。 |

### 6. `solarcell_parse_results`

只解析已有 backend 输出。默认按 SCAPS 输出格式解析。

| 字段 | 说明 |
|---|---|
| 输入 | backend、output folder 或文件列表 |
| 输出 | metrics、curves、profiles、warnings |
| 用途 | 用于历史数据整理、回归测试，或解析已由 Wine/Windows runner 生成的输出。 |

### 7. `solarcell_get_artifact`

获取某次运行的原始文件或结构化结果。

| 字段 | 说明 |
|---|---|
| 输入 | `run_id`、artifact type |
| 输出 | 文件路径、摘要、CSV/JSON 内容片段 |
| 用途 | 让 agent 可以追溯输入、查看曲线、生成报告。 |

## 输入 Schema 草案

第一版 schema 不要追求覆盖所有太阳电池模拟器能力，先覆盖钙钛矿太阳电池最常用的 `J-V` 和 sweep。通用 schema 里保留 `backend` 字段，默认值是 `scaps`。

```ts
type SimulationInput = {
  name: string;
  backend?: "scaps" | "wxamps" | "setfos" | "custom_python" | "surrogate_model";
  backendOptions?: {
    runner?: "wine" | "windows_native";
    executablePath?: string;
    wineBin?: string;
    winePrefix?: string;
    extraArgs?: string[];
  };
  device: {
    architecture: "n-i-p" | "p-i-n" | "custom";
    layers: SimulationLayer[];
    frontContact: SimulationContact;
    backContact: SimulationContact;
  };
  conditions: {
    temperatureK: number;
    illumination: "AM1.5G" | "custom" | "dark";
    incidentSide: "front" | "back";
    voltageScan: {
      startV: number;
      stopV: number;
      stepV: number;
    };
  };
  measurements: Array<"JV" | "QE" | "CV" | "CF" | "BANDS">;
  sweep?: SimulationSweep;
  provenance?: {
    parameterSources?: string[];
    notes?: string;
  };
};

type SimulationLayer = {
  name: string;
  role: "TCO" | "ETL" | "absorber" | "HTL" | "metal" | "other";
  thicknessNm: number;
  material: {
    bandgapEv: number;
    electronAffinityEv: number;
    relativePermittivity: number;
    ncCm3: number;
    nvCm3: number;
    electronMobilityCm2Vs: number;
    holeMobilityCm2Vs: number;
    donorDensityCm3?: number;
    acceptorDensityCm3?: number;
    absorptionFile?: string;
  };
  defects?: SimulationDefect[];
};
```

## 输出 Schema 草案

```ts
type SimulationResult = {
  runId: string;
  backend: string;
  backendVersion?: string;
  runner: string;
  status: "success" | "failed" | "partial" | "config_required";
  metrics?: {
    pcePercent?: number;
    vocV?: number;
    jscMaCm2?: number;
    ffPercent?: number;
    vmppV?: number;
    jmppMaCm2?: number;
  };
  curves?: {
    jv?: TableRef;
    qe?: TableRef;
    cv?: TableRef;
    cf?: TableRef;
  };
  profiles?: {
    bands?: TableRef;
    recombination?: TableRef;
    electricField?: TableRef;
    carrierDensity?: TableRef;
  };
  diagnostics: Array<{
    severity: "info" | "warning" | "error";
    code: string;
    message: string;
  }>;
  artifacts: Array<{
    type: "input" | "raw_output" | "parsed_csv" | "plot" | "log";
    path: string;
  }>;
  environment?: {
    executablePath?: string;
    wineBin?: string;
    winePrefix?: string;
  };
};
```

## Runner 策略

SCAPS 最大的不确定性不是物理模型，而是自动化执行方式。SCAPS 是 Windows-based 软件，第一版需要假设：

- wrapper 不分发 SCAPS 安装包或可执行文件。
- 用户需要自己把 SCAPS executable 放到指定路径。
- wrapper 通过配置读取 `scaps.exe` 路径。
- macOS/Linux 默认用 Wine 作为虚拟运行环境。
- 如果用户在 Windows 上运行，可以走 native Windows runner。

建议先定义统一 `Runner` 接口，再逐步替换实现。

```text
Runner.prepare(case)
Runner.run(case, timeout)
Runner.collect(case)
Runner.cleanup(case)
```

| Runner                     | 阶段  | 作用                                | 优点                               | 风险                                    |
| -------------------------- | --- | --------------------------------- | -------------------------------- | ------------------------------------- |
| `WineScapsRunner`          | P0  | 用 Wine 启动用户配置的 SCAPS executable   | 适合 macOS/Linux；不要求用户有 Windows 主机 | 需要验证 SCAPS 在 Wine 下的脚本/批处理能力和文件路径映射。  |
| `NativeWindowsScapsRunner` | P1  | 在 Windows 环境直接运行 SCAPS executable | 最接近 SCAPS 原生环境                   | 用户必须在 Windows 上部署 package/MCP server。 |

推荐路线：第一版直接实现 `WineScapsRunner`。`WineScapsRunner` 是 macOS/Linux 默认路径。

## SCAPS Backend 配置

SCAPS backend 必须显式配置 executable 路径。wrapper 不应该假设系统里已经安装了 SCAPS，也不应该把 SCAPS executable 放进仓库。

### 用户需要准备的文件

建议约定一个清晰目录，例如：

```text
~/.local/share/solarcell-sim/backends/scaps/
  SCAPS/
    scaps.exe
    other_scaps_files_if_needed/
```

也可以允许项目内路径：

```text
./external/scaps/
  scaps.exe
```

这些目录只作为约定，不由 package 自动下载 SCAPS。用户需要自己放置文件，并确认许可证/使用权限。

### 配置优先级

按以下顺序解析配置：

1. 函数参数或 MCP tool 参数里的 `backendOptions`。
2. 项目配置文件 `.solarcell-sim.toml`。
3. 用户全局配置 `~/.config/solarcell-sim/config.toml`。
4. 环境变量。
5. package 默认值。

示例配置：

```toml
[backend]
default = "scaps"

[backends.scaps]
runner = "wine"
executable_path = "/Users/longhan/.local/share/solarcell-sim/backends/scaps/SCAPS/scaps.exe"
workdir = "/Users/longhan/.local/share/solarcell-sim/runs"

[backends.scaps.wine]
bin = "wine"
prefix = "/Users/longhan/.wine-scaps"
```

对应环境变量：

```text
SOLARCELL_SIM_BACKEND=scaps
SCAPS_EXECUTABLE_PATH=/path/to/scaps.exe
SCAPS_WORKDIR=/path/to/runs
WINE_BIN=wine
WINEPREFIX=/path/to/wineprefix
```

### 配置检查

`solarcell_check_backend(backend="scaps")` 至少检查：

| 检查项 | 成功条件 | 失败处理 |
|---|---|---|
| SCAPS executable path | 路径存在且可读 | 返回 `status=config_required`，提示用户配置路径。 |
| Wine binary | macOS/Linux 下 `wine` 可执行 | 返回配置错误或建议安装 Wine。 |
| Wine prefix | 不存在时可创建，或存在且可写 | 返回 warning/error。 |
| Workdir | 可创建、可写 | 返回 error。 |
| 版本探测 | 能读取 SCAPS 版本则记录 | 不能读取时 warning，不阻塞 P0/P1。 |

### Wine 路径映射

SCAPS backend 内部要避免把 macOS/Linux 路径直接写进 Windows 程序无法识别的地方。需要一个路径映射层：

```text
/Users/longhan/.../runs/case_001
  -> Z:\Users\longhan\...\runs\case_001
```

renderer 和 runner 的职责边界：

- `renderer` 生成 backend-neutral 或 SCAPS 输入文件。
- `runner` 负责把 host path 转换成 Wine/Windows path。
- `parser` 始终读取 host filesystem 上的输出文件。

## MCP Docker 部署

MCP server 可以使用 Docker 部署，而且建议第一版优先支持 Docker 部署。Docker 负责固定 Python package、MCP server、Wine、字体/图形运行依赖和系统库；SCAPS executable 由用户自行放置并通过 volume 挂载进去。

### 适合 Docker 化的部分

| 部分 | 是否放进镜像 | 说明 |
|---|---|---|
| `solarcell_sim` Python package | 是 | wrapper 的核心逻辑。 |
| `solarcell_sim_mcp` MCP server | 是 | 作为 agent 调用入口。 |
| Wine | 是 | macOS/Linux/Docker 下运行 SCAPS 的默认环境。 |
| Python 依赖 | 是 | Pydantic、pandas、numpy、MCP SDK 等。 |
| SCAPS executable | 否 | 用户自行下载/授权/放置，通过 volume 挂载。 |
| run artifacts | 否 | 通过 volume 挂载，保证运行结果可持久化。 |
| Wine prefix | 建议否 | 可挂载持久化，避免每次容器启动都重新初始化。 |

### 推荐容器结构

```text
Docker image
  /app/solarcell_sim
  /app/solarcell_sim_mcp
  /opt/wine

Mounted volumes
  /scaps        -> 用户放置 scaps.exe 和相关文件
  /runs         -> 每次仿真的输入、输出、日志、解析结果
  /wineprefix   -> Wine prefix，可选但推荐持久化
```

### 环境变量

```text
SOLARCELL_SIM_BACKEND=scaps
SCAPS_EXECUTABLE_PATH=/scaps/scaps.exe
SCAPS_WORKDIR=/runs
WINE_BIN=wine
WINEPREFIX=/wineprefix
```

如果 SCAPS 需要图形环境才能启动，即使使用脚本/批处理运行，也可以在镜像里预装 `xvfb`，由 runner 用 `xvfb-run wine ...` 启动。这个路径仍然属于 `WineScapsRunner`，不引入 GUI 自动化 runner。

### Dockerfile 草案

```dockerfile
FROM python:3.11-slim

RUN dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
      wine wine32 wine64 xvfb fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md /app/
COPY src /app/src
RUN pip install --no-cache-dir .

ENV SOLARCELL_SIM_BACKEND=scaps
ENV SCAPS_EXECUTABLE_PATH=/scaps/scaps.exe
ENV SCAPS_WORKDIR=/runs
ENV WINE_BIN=wine
ENV WINEPREFIX=/wineprefix

ENTRYPOINT ["python", "-m", "solarcell_sim_mcp.server"]
```

### Docker Compose 草案

```yaml
services:
  solarcell-sim-mcp:
    build: .
    image: solarcell-sim-mcp:latest
    environment:
      SOLARCELL_SIM_BACKEND: scaps
      SCAPS_EXECUTABLE_PATH: /scaps/scaps.exe
      SCAPS_WORKDIR: /runs
      WINE_BIN: wine
      WINEPREFIX: /wineprefix
    volumes:
      - ./external/scaps:/scaps:ro
      - ./runs:/runs
      - ./wineprefix:/wineprefix
    stdin_open: true
    tty: false
```

### MCP 客户端启动方式

如果 MCP 使用 stdio transport，客户端可以通过 Docker 启动 server：

```json
{
  "mcpServers": {
    "solarcell-sim": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "-v", "/path/to/scaps:/scaps:ro",
        "-v", "/path/to/runs:/runs",
        "-v", "/path/to/wineprefix:/wineprefix",
        "-e", "SCAPS_EXECUTABLE_PATH=/scaps/scaps.exe",
        "-e", "SCAPS_WORKDIR=/runs",
        "-e", "WINEPREFIX=/wineprefix",
        "solarcell-sim-mcp:latest"
      ]
    }
  }
}
```

如果后续 MCP server 改成 HTTP/SSE transport，可以用 `docker compose up` 常驻运行，再让 agent 连接固定端口。

### Docker 部署注意事项

- 镜像不包含 SCAPS executable，避免许可证和分发问题。
- `SCAPS_EXECUTABLE_PATH` 必须指向容器内部路径，而不是宿主机路径。
- `/runs` 必须挂载成可写 volume，否则仿真结果和日志会随容器删除。
- Wine prefix 建议持久化，否则首次运行可能慢且不稳定。
- 如果 SCAPS 在 Wine 下需要图形初始化，runner 应自动检测并启用 `xvfb-run`。
- Docker 只解决运行环境一致性，不解决 SCAPS 脚本接口本身是否稳定的问题。