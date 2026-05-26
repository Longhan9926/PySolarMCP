FROM python:3.11-slim

RUN dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
      wine wine32 wine64 xvfb fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md /app/
COPY src /app/src
RUN pip install --no-cache-dir ".[mcp]"

ENV SOLARCELL_SIM_BACKEND=scaps
ENV SCAPS_EXECUTABLE_PATH=/scaps/scaps.exe
ENV SCAPS_DEFINITION_PATH=/definitions/baseline.scaps
ENV SCAPS_WORKDIR=/runs
ENV WINE_BIN=wine
ENV WINEPREFIX=/wineprefix

ENTRYPOINT ["python", "-m", "solarcell_sim_mcp.server"]
