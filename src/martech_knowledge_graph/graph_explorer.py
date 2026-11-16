"""
Martech knowledge graph — loading and extraction library.

Loads the ontology + instance turtle files into one in-memory rdflib graph
and extracts a vis-network-friendly {nodes, edges} structure from it. This
is used directly by server.py to power the web UI's live graph view
(GET /api/graph-data) and component/journey listings -- there is no
standalone CLI here; the web UI (`martech-knowledge-graph serve`) is the
only supported way to explore or visualize the graph.

Dependencies:
    pip install rdflib
"""

from pathlib import Path

import rdflib
from rdflib import RDF, RDFS, Namespace

# --------------------------------------------------------------------------
# Config — the ontology is always the one bundled with this package. The
# default instance data (script_dir passed to load_graph()) is the bundled
# examples/ folder; server.py always passes an explicit script_dir (the
# active demo/org workspace) instead of relying on this default.
# --------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
ONTOLOGY_FILE = SCRIPT_DIR / "ontology" / "martech-ontology.ttl"
EXAMPLES_DIR = SCRIPT_DIR / "examples"

MARTECH = Namespace("https://example.org/martech/ontology/")

# Object-property edges worth drawing (literal/datatype properties like
# order, status, formula are skipped — they clutter the layout without
# adding graph structure)
RELATIONSHIP_PREDICATES = [
    "has_stage", "rolls_up_to", "maps_to",
    "addressed_by", "measured_entity", "measured_component", "based_on",
]


def load_graph(ontology_path=ONTOLOGY_FILE, script_dir=EXAMPLES_DIR):
    """
    Load the ontology plus every '*-instances.ttl' file found in script_dir
    into a single in-memory graph. Adding a new journey means dropping a new
    <slug>-instances.ttl file into that directory -- nothing in the code
    needs to change.
    """
    g = rdflib.Graph()
    g.parse(ontology_path, format="turtle")

    instance_files = sorted(Path(script_dir).glob("*-instances.ttl"))
    for path in instance_files:
        g.parse(path, format="turtle")

    return g


# --------------------------------------------------------------------------
# Component activation. A CJA sync pulls in every component of a data view;
# only the ones someone activated (or curated, or uses) count for pickers,
# the graph view and agents. One rule, applied to any graph:
#   - measured by a stage (journey or shared)  -> active, always
#   - martech:active true / false              -> that
#   - no flag                                  -> active once it has curated context
# --------------------------------------------------------------------------

CURATED_PREDICATES = ("definition", "caveats", "context", "owner")


def used_components(g):
    """Every component a Measurement measures, from a journey stage or a shared stage."""
    return set(g.objects(None, MARTECH.measured_component))


def is_curated(g, component):
    return any(str(o).strip() for p in CURATED_PREDICATES for o in g.objects(component, MARTECH[p]))


def inactive_components(g):
    """URIs of the components in g that are inactive under the rule above."""
    used = used_components(g)
    inactive = set()
    for c in g.subjects(RDF.type, MARTECH.Component):
        if c in used:
            continue
        flag = g.value(c, MARTECH.active)
        active = flag.toPython() is True if flag is not None else is_curated(g, c)
        if not active:
            inactive.add(c)
    return inactive


def without_inactive_components(g, inactive=None):
    """A copy of g without inactive components: their own triples and anything pointing at them (a data
    layer variable's maps_to). What agents see."""
    inactive = inactive_components(g) if inactive is None else inactive
    out = rdflib.Graph()
    for prefix, ns in g.namespaces():
        out.bind(prefix, ns)
    for s, p, o in g:
        if s not in inactive and o not in inactive:
            out.add((s, p, o))
    return out


def filtered_instance_text(path, inactive):
    """The file's Turtle without inactive components, or None when it holds none of them (copy it as is)."""
    fg = rdflib.Graph()
    fg.parse(path, format="turtle")
    if not any(s in inactive or o in inactive for s, _, o in fg):
        return None
    return without_inactive_components(fg, inactive).serialize(format="turtle")


def _local_name(uri):
    s = str(uri)
    return s.rstrip("/").split("/")[-1].split("#")[-1]


def _label(g, node):
    lbl = g.value(node, RDFS.label)
    return str(lbl) if lbl else _local_name(node)


def extract_full_graph(g):
    """
    Extract every instance node and every relationship edge into a
    vis-network-friendly structure. For each node, also pulls every
    literal (datatype) property it has -- generic, not hardcoded per
    node type, so a Stage's 'order' and a Component's 'definition'
    both surface the same way.
    """
    class_uris = set(g.subjects(RDF.type, RDFS.Class))
    prop_uris = set(g.subjects(RDF.type, RDF.Property))

    instances = set()
    for s, p, o in g:
        if p == RDF.type and str(o).startswith(str(MARTECH)):
            if s not in class_uris and s not in prop_uris:
                instances.add(s)

    nodes = []
    for inst in instances:
        types = list(g.objects(inst, RDF.type))
        tname = _local_name(types[0]) if types else "?"
        props = {}
        for p, o in g.predicate_objects(inst):
            if isinstance(o, rdflib.Literal):
                pname = _local_name(p)
                if pname != "label":
                    props[pname] = str(o)
            elif p == MARTECH.refs:
                # refs is a URI, not a literal -- special-cased since it's
                # the component's identity/ID and shouldn't be silently
                # dropped just because it isn't a plain string value.
                props["refs"] = str(o)
        nodes.append({
            "id": str(inst),
            "label": _label(g, inst),
            "group": tname,
            "properties": props,
        })

    edges = []
    for inst in instances:
        for pred in RELATIONSHIP_PREDICATES:
            for o in g.objects(inst, MARTECH[pred]):
                if o in instances:
                    edges.append({"from": str(inst), "to": str(o), "label": pred})

    return {"nodes": nodes, "edges": edges}


def extract_ontology_schema(g):
    """
    Programmatic version of what's hand-written into ui/ontology.html: every
    rdfs:Class and rdf:Property in the graph, with their comment and (for
    properties) domain/range -- so a caller (e.g. the MCP server's
    get_ontology_schema tool) always reflects the real ontology file instead
    of a description that can drift out of sync with it.
    """
    classes = []
    for s in sorted(g.subjects(RDF.type, RDFS.Class), key=_local_name):
        comment = g.value(s, RDFS.comment)
        classes.append({
            "name": _local_name(s),
            "comment": str(comment) if comment else None,
        })

    properties = []
    for s in sorted(g.subjects(RDF.type, RDF.Property), key=_local_name):
        comment = g.value(s, RDFS.comment)
        domain = g.value(s, RDFS.domain)
        range_ = g.value(s, RDFS.range)
        properties.append({
            "name": _local_name(s),
            "domain": _local_name(domain) if domain else None,
            "range": _local_name(range_) if range_ else None,
            "comment": str(comment) if comment else None,
        })

    return {"classes": classes, "properties": properties}
