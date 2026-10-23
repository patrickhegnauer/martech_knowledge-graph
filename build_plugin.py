"""Build the Coworker plugin in plugins/martech-kg from the knowledge graph source files.

Run after any change to the ontology or the instance files. The plugin folder is regenerated,
so do not edit it by hand. To build a plugin into another repository (e.g. your organization's
private one), use `martech-knowledge-graph build-plugin --out ...` instead.
"""

import argparse
from pathlib import Path

from martech_knowledge_graph import graph_explorer as ge
from martech_knowledge_graph.plugin_builder import build_plugin

REPO_ROOT = Path(__file__).resolve().parent
PLUGIN_DIR = REPO_ROOT / "plugins" / "martech-kg"
NAME = "martech-kg"
DESCRIPTION = ("Martech knowledge graph as a skill: journeys, KPIs, requirements, components, data layer "
               "variables, caveats and owners.")
SKILL_DESCRIPTION = (
    "Use when the user asks about the martech / customer experience knowledge graph: customer journeys and "
    "their stages, KPIs and the requirements behind them, the components (metrics and dimensions) that measure "
    "them, data layer variables, and component definitions, caveats and owners. Also use to trace a KPI back "
    "to its tracking, or to check what a component or data layer variable feeds."
)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=ge.EXAMPLES_DIR,
                        help="Folder with *-instances.ttl files. Default: the bundled generic demo data.")
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()

    if not any(data_dir.glob("*-instances.ttl")):
        raise SystemExit(f"No *-instances.ttl files found in {data_dir}")
    if data_dir != ge.EXAMPLES_DIR.resolve():
        print("WARNING: building from a non-bundled data folder. The output will contain that data;")
        print("         do not commit references/ to a public repository.")

    sources, triples = build_plugin(data_dir, PLUGIN_DIR, NAME, DESCRIPTION, skill_description=SKILL_DESCRIPTION,
                                    author="Hegi", keywords=["knowledge-graph", "martech", "rdf", "analytics"])

    print(f"Copied {len(sources)} file(s) into {(PLUGIN_DIR / 'skills' / NAME / 'references').relative_to(REPO_ROOT)}:")
    for name in sources:
        print(f"  - {name}")
    print(f"Triple count: {triples}")


if __name__ == "__main__":
    main()
