from __future__ import annotations

import argparse
import sys
from typing import Any

from solarcell_sim_mcp.tools import (
    solarcell_check_backend,
    solarcell_get_artifact,
    solarcell_parse_results,
    solarcell_prepare_case,
    solarcell_run_case,
    solarcell_run_sweep,
    solarcell_validate_input,
)


def build_server() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "The MCP SDK is not installed. Install with `pip install .[mcp]` or use the Docker image."
        ) from exc

    server = FastMCP("solarcell-sim")
    server.tool(name="solarcell_check_backend")(solarcell_check_backend)
    server.tool(name="solarcell_validate_input")(solarcell_validate_input)
    server.tool(name="solarcell_prepare_case")(solarcell_prepare_case)
    server.tool(name="solarcell_run_case")(solarcell_run_case)
    server.tool(name="solarcell_run_sweep")(solarcell_run_sweep)
    server.tool(name="solarcell_parse_results")(solarcell_parse_results)
    server.tool(name="solarcell_get_artifact")(solarcell_get_artifact)
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the PySolarMCP stdio server.")
    parser.add_argument("--check", action="store_true", help="Validate that the server can be constructed, then exit.")
    args = parser.parse_args(argv)

    try:
        server = build_server()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.check:
        print("solarcell-sim MCP server is ready")
        return 0

    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

