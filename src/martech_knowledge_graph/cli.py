"""Command-line entry point: `martech-knowledge-graph serve`."""

import argparse
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

    args = parser.parse_args()

    if args.command == "serve":
        data_dir = Path(args.data_dir).resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        app = server.create_app(data_dir)
        print(f"Data directory: {data_dir}")
        print(f"Serving on http://{args.host}:{args.port}/")
        app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
