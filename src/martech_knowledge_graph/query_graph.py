"""
Martech knowledge graph — query samples

A lighter-weight companion to graph_explorer.py, focused only on
querying (no visualization). Add your own queries to the QUERIES
dict below and re-run.

Dependencies:
    pip install rdflib

Loads the ontology bundled with this package plus the bundled example
instance data by default. Run standalone:
    python -m martech_knowledge_graph.query_graph
"""

from pathlib import Path
import rdflib

SCRIPT_DIR = Path(__file__).resolve().parent
ONTOLOGY_FILE = SCRIPT_DIR / "ontology" / "martech-ontology.ttl"
EXAMPLES_DIR = SCRIPT_DIR / "examples"

QUERIES = {
    "Everything about the Order stage": """
        PREFIX martech: <https://example.org/martech/ontology/>
        SELECT ?predicate ?value WHERE {
          <https://example.org/martech/data/ecommerce/stage_order> ?predicate ?value .
        }
    """,
    "Full chain: Requirement -> KPI -> Stage -> Component": """
        PREFIX martech: <https://example.org/martech/ontology/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?reqLabel ?kpiLabel ?stageLabel ?compLabel WHERE {
          ?req a martech:Requirement ; rdfs:label ?reqLabel ; martech:addressed_by ?kpi .
          ?kpi rdfs:label ?kpiLabel .
          ?stage a martech:Stage ; rdfs:label ?stageLabel ; martech:rolls_up_to ?kpi .
          ?m martech:measured_entity ?stage ; martech:measured_component ?comp .
          ?comp rdfs:label ?compLabel .
        }
    """,
    "What does this data layer variable feed?": """
        PREFIX martech: <https://example.org/martech/ontology/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?dlvLabel ?compLabel WHERE {
          ?dlv a martech:DataLayerVariable ; rdfs:label ?dlvLabel ; martech:maps_to ?comp .
          ?comp rdfs:label ?compLabel .
        }
    """,
    "All stages in order": """
        PREFIX martech: <https://example.org/martech/ontology/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?order ?stageLabel WHERE {
          ?stage a martech:Stage ; martech:order ?order ; rdfs:label ?stageLabel .
        } ORDER BY ?order
    """,
}


def load_graph(ontology_path=ONTOLOGY_FILE, script_dir=EXAMPLES_DIR):
    g = rdflib.Graph()
    g.parse(ontology_path, format="turtle")
    for path in sorted(Path(script_dir).glob("*-instances.ttl")):
        print(f"Loading {path.name}")
        g.parse(path, format="turtle")
    return g


def run_all(g):
    for name, query in QUERIES.items():
        print(f"\n=== {name} ===")
        results = list(g.query(query))
        if not results:
            print("(no results)")
            continue
        for row in results:
            print(" | ".join(str(v) for v in row))


if __name__ == "__main__":
    g = load_graph()
    print(f"Loaded graph: {len(g)} triples\n")
    run_all(g)
