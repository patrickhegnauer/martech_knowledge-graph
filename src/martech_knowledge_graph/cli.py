"""Command-line entry point: `martech-knowledge-graph serve` / `mcp` / `export-mcp` / `build-plugin`."""

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

    export_parser = subparsers.add_parser(
        "export-mcp",
        help="Write a self-contained folder you can push to GitHub and deploy on Prefect Horizon.",
    )
    export_parser.add_argument("--out", required=True, help="Output folder (created if missing).")
    export_parser.add_argument(
        "--data-dir", default="./martech-knowledge-graph-data",
        help="Org workspace to snapshot. Default: %(default)s",
    )
    export_parser.add_argument(
        "--demo", action="store_true", help="Export the bundled demo data instead (for a test deploy)."
    )
    export_parser.add_argument("--name", default="martech-knowledge-graph", help="Title used in the README.")

    plugin_parser = subparsers.add_parser(
        "build-plugin",
        help="Write a Coworker plugin folder (plugin.json, SKILL.md, references/) built from the graph.",
    )
    plugin_parser.add_argument("--out", required=True,
                               help="Plugin folder to write, e.g. plugins/my-context. Regenerated on every build.")
    plugin_parser.add_argument(
        "--data-dir", default="./martech-knowledge-graph-data",
        help="Org workspace to build from. Default: %(default)s",
    )
    plugin_parser.add_argument(
        "--demo", action="store_true", help="Build from the bundled demo data instead."
    )
    plugin_parser.add_argument("--name", default="martech-kg", help="Plugin and skill name. Default: %(default)s")
    plugin_parser.add_argument(
        "--description",
        default="Martech knowledge graph as a skill: journeys, KPIs, requirements, components, data layer "
                "variables, caveats and owners.",
        help="Plugin description, also used as the skill description.",
    )
    plugin_parser.add_argument("--version", help="Plugin version written to plugin.json, e.g. 0.1.0.")
    plugin_parser.add_argument(
        "--skill-name",
        help="Name of the generated skill, if it differs from the plugin name. Other skills in the plugin's "
             "skills/ folder are left untouched, so hand-written skills can live in the same plugin. "
             "Default: same as --name",
    )
    plugin_parser.add_argument("--skill-description",
                               help="Description of the generated skill. Default: same as --description")

    args = parser.parse_args()

    if args.command == "serve":
        data_dir = Path(args.data_dir).resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        app = server.create_app(data_dir)
        print(f"Data directory: {data_dir}")
        print(f"Serving on http://{args.host}:{args.port}/")
        app.run(host=args.host, port=args.port, debug=args.debug)

    elif args.command == "export-mcp":
        from . import export, graph_explorer

        source = graph_explorer.EXAMPLES_DIR if args.demo else Path(args.data_dir).resolve()
        out = Path(args.out).resolve()
        out.mkdir(parents=True, exist_ok=True)
        count = export.export_mcp_project(out, source, args.name)
        print(f"Exported {count} data file(s) from {source} to {out}")
        print("Next: push that folder to a PRIVATE GitHub repo and deploy it on Prefect Horizon "
              f"(entrypoint server.py:mcp). See {out / 'README.md'}")

    elif args.command == "build-plugin":
        from . import graph_explorer, plugin_builder

        source = graph_explorer.EXAMPLES_DIR if args.demo else Path(args.data_dir).resolve()
        out = Path(args.out).resolve()
        if not any(source.glob("*-instances.ttl")):
            print(f"Note: no *-instances.ttl files in {source}; the plugin will contain the ontology only.")
        sources, triples = plugin_builder.build_plugin(
            source, out, args.name, args.description, version=args.version,
            skill_name=args.skill_name, skill_description=args.skill_description,
        )
        print(f"Built plugin '{args.name}' in {out} from {len(sources)} file(s), {triples} triples.")
        if not args.demo:
            print("The plugin contains your data: keep it in a private repository.")

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
