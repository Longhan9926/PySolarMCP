FROM python:3.11-slim

RUN dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
      wine wine32 xvfb xauth fonts-dejavu \
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
ENV WINEARCH=win32
ENV SOLARCELL_SIM_XVFB=1

EXPOSE 31335

ENTRYPOINT ["python", "-m", "solarcell_sim_mcp.server"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "31335", "--path", "/mcp"]
