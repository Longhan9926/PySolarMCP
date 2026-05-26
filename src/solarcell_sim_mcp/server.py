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


def build_server(host: str = "127.0.0.1", port: int = 31335, path: str = "/mcp") -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "The MCP SDK is not installed. Install with `pip install .[mcp]` or use the Docker image."
        ) from exc

    server = FastMCP("solarcell-sim", host=host, port=port, streamable_http_path=path)
    server.tool(name="solarcell_check_backend")(solarcell_check_backend)
    server.tool(name="solarcell_validate_input")(solarcell_validate_input)
    server.tool(name="solarcell_prepare_case")(solarcell_prepare_case)
    server.tool(name="solarcell_run_case")(solarcell_run_case)
    server.tool(name="solarcell_run_sweep")(solarcell_run_sweep)
    server.tool(name="solarcell_parse_results")(solarcell_parse_results)
    server.tool(name="solarcell_get_artifact")(solarcell_get_artifact)
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the PySolarMCP MCP server.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport to use. Use streamable-http for remote MCP deployments.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host for streamable-http.")
    parser.add_argument("--port", type=int, default=31335, help="HTTP bind port for streamable-http.")
    parser.add_argument("--path", default="/mcp", help="HTTP MCP path for streamable-http.")
    parser.add_argument("--check", action="store_true", help="Validate that the server can be constructed, then exit.")
    args = parser.parse_args(argv)

    try:
        server = build_server(host=args.host, port=args.port, path=args.path)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.check:
        endpoint = f"http://{args.host}:{args.port}{args.path}" if args.transport == "streamable-http" else "stdio"
        print(f"solarcell-sim MCP server is ready ({args.transport}: {endpoint})")
        return 0

    server.run(transport=args.transport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

