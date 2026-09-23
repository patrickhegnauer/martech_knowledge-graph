"""Command-line entry point: `martech-knowledge-graph serve` / `martech-knowledge-graph mcp`."""

import argparse
import sys
from pathlib import Path

from . import server


def main():
    parser = argparse.ArgumentParser(prog="martech-knowledge-graph")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="Run the local API + UI server.")
    serve_parser.add_argument(
        "--data-dir",
        default="./martech-knowledge-graph-data",
        help="Directory holding your *-instances.ttl files (created if missing). Default: %(default)s",
    )
    serve_parser.add_argument("--host", default="127.0.0.1", help="Default: %(default)s")
    serve_parser.add_argument("--port", type=int, default=5055, help="Default: %(default)s")
    serve_parser.add_argument(
        "--debug", action="store_true", help="Enable Flask debug mode (not recommended outside local dev)."
    )

    mcp_parser = subparsers.add_parser(
        "mcp", help="Run the MCP server (run_sparql + get_ontology_schema)."
    )
    mcp_parser.add_argument(
        "--data-dir",
        default="./martech-knowledge-graph-data",
        help="Same org workspace `serve` uses -- shares its .mkg-mode file, so switching demo/org "
             "in the browser is reflected here too. Default: %(default)s",
    )
    mcp_parser.add_argument(
        "--transport", choices=["http", "stdio"], default="http",
        help="'http' (default) runs a persistent server at a URL, for clients that connect over the "
             "network (e.g. a remote client, or a URL pasted into a connectors UI). 'stdio' is spawned "
             "directly by a local MCP client instead (e.g. Claude Desktop's local server config, not its "
             "remote/Connectors URL field) -- no network, no URL, no --host/--port. Default: %(default)s",
    )
    mcp_parser.add_argument(
        "--host", default="127.0.0.1",
        help="Only used for --transport http. Default: %(default)s. There is no authentication -- only "
             "change this if you understand who else that exposes the graph to.",
    )
    mcp_parser.add_argument(
        "--port", type=int, default=8931,
        help="Only used for --transport http. Default: %(default)s",
    )

    args = parser.parse_args()

    if args.command == "serve":
        data_dir = Path(args.data_dir).resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        app = server.create_app(data_dir)
        print(f"Data directory: {data_dir}")
        print(f"Serving on http://{args.host}:{args.port}/")
        app.run(host=args.host, port=args.port, debug=args.debug)

    elif args.command == "mcp":
        from . import mcp_server

        data_dir = Path(args.data_dir).resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        mcp = mcp_server.create_mcp(data_dir)

        if args.transport == "stdio":
            # stdio IS the protocol channel -- anything printed to stdout here
            # would corrupt it. Status output goes to stderr instead, and the
            # banner is explicitly disabled rather than trusted to do the
            # same (verified empirically, not just assumed).
            print(f"Data directory: {data_dir}", file=sys.stderr, flush=True)
            print("Starting MCP server over stdio...", file=sys.stderr, flush=True)
            mcp.run(transport="stdio", show_banner=False)
        else:
            print(f"Data directory: {data_dir}", flush=True)
            print(f"MCP server ready at http://{args.host}:{args.port}/mcp", flush=True)
            mcp.run(transport="http", host=args.host, port=args.port, path="/mcp", show_banner=False)


if __name__ == "__main__":
    main()
