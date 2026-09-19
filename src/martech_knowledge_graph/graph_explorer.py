"""
Martech knowledge graph — query + visualization

Loads the ontology + instance turtle files into one in-memory graph,
runs a sample SPARQL query against them, renders a filtered PNG, and
writes two standalone HTML explorers (a journey-focused view and a
full interactive network view).

Dependencies:
    pip install rdflib

The PNG step also needs the Graphviz system binary (the `dot` command)
on your PATH -- separate from the pip package:
    - Windows: https://graphviz.org/download/ (or `choco install graphviz`)
    - Mac:     brew install graphviz
    - Linux:   apt install graphviz

This standalone script's network view (graph_network.html) is separate from
the `martech-knowledge-graph serve` web UI, which already bundles vis-network
and needs none of this. This script's own graph_network.html output needs
the vis-network JS library installed locally (not loaded from a CDN, since
that's commonly blocked on corporate networks) -- one-time setup, run from
wherever you're invoking this script:
    npm install vis-network
This creates a node_modules/ folder that graph_network.html references
directly -- nothing else to configure.
"""

import json
import subprocess
from pathlib import Path

import rdflib
from rdflib import RDF, RDFS, Namespace

# --------------------------------------------------------------------------
# Config — the ontology is always the one bundled with this package. The
# default instance data (script_dir passed to load_graph()) is the bundled
# examples/ folder, so running this standalone produces something useful
# out of the box; pass a different script_dir to load_graph() to point it
# at your own data directory instead. Output files are written to the
# current working directory, not next to this installed script (which is
# typically read-only once pip-installed).
# --------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
ONTOLOGY_FILE = SCRIPT_DIR / "ontology" / "martech-ontology.ttl"
EXAMPLES_DIR = SCRIPT_DIR / "examples"
OUTPUT_DOT = Path.cwd() / "graph.dot"
OUTPUT_PNG = Path.cwd() / "graph.png"
OUTPUT_HTML = Path.cwd() / "explorer.html"
OUTPUT_GRAPH_HTML = Path.cwd() / "graph_network.html"

MARTECH = Namespace("https://example.org/martech/ontology/")

# Colors per class, used only by the visualization step
NODE_COLORS = {
    "Requirement": "#ffc9c9",
    "KPI": "#99e9d2",
    "Journey": "#ffd8a8",
    "Stage": "#ffa8a8",
    "Feature": "#eebefa",
    "Component": "#d0bfff",
    "DataLayerVariable": "#fcc2d7",
    "Measurement": "#e9ecef",
    "StageTransition": "#e9ecef",
}

# Object-property edges worth drawing (literal/datatype properties like
# order, status, formula are skipped — they clutter the layout without
# adding graph structure)
RELATIONSHIP_PREDICATES = [
    "has_stage", "uses_feature", "rolls_up_to", "contributes_to", "maps_to",
    "addressed_by", "measured_entity", "measured_component",
    "transition_from", "transition_to",
]


def load_graph(ontology_path=ONTOLOGY_FILE, script_dir=EXAMPLES_DIR):
    """
    Load the ontology plus every '*-instances.ttl' file found next to this
    script into a single in-memory graph. Adding a new journey means
    dropping a new <slug>-instances.ttl file here -- nothing in the code
    needs to change.
    """
    g = rdflib.Graph()
    g.parse(ontology_path, format="turtle")

    instance_files = sorted(script_dir.glob("*-instances.ttl"))
    if not instance_files:
        print("Warning: no *-instances.ttl files found next to this script.")
    for path in instance_files:
        print(f"Loading {path.name}")
        g.parse(path, format="turtle")

    return g


def run_sample_query(g):
    """
    Sample SPARQL query: walk Stage -> Measurement -> Component -> refs,
    returning the full funnel in order. Swap this query out for whatever
    you actually want to ask the graph.
    """
    query = """
    PREFIX martech: <https://example.org/martech/ontology/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?order ?stageLabel ?componentLabel ?ref WHERE {
      ?stage a martech:Stage ; martech:order ?order ; rdfs:label ?stageLabel .
      ?m a martech:Measurement ;
         martech:measured_entity ?stage ;
         martech:measured_component ?comp .
      ?comp rdfs:label ?componentLabel ; martech:refs ?ref .
    } ORDER BY ?order
    """
    print("\n--- Sample query: funnel stages -> components ---")
    for row in g.query(query):
        print(f"{row.order}. {row.stageLabel:15} -> {row.componentLabel:20} ({row.ref})")


def _local_name(uri):
    s = str(uri)
    return s.rstrip("/").split("/")[-1].split("#")[-1]


def _label(g, node):
    lbl = g.value(node, RDFS.label)
    return str(lbl) if lbl else _local_name(node)


def build_dot(g):
    """
    Build a filtered DOT representation: only instances (not ontology
    classes/properties) and only object-property edges. This is what
    keeps the rendered graph readable instead of a giant literal dump.
    """
    class_uris = set(g.subjects(RDF.type, RDFS.Class))
    prop_uris = set(g.subjects(RDF.type, RDF.Property))

    instances = set()
    for s, p, o in g:
        if p == RDF.type and str(o).startswith(str(MARTECH)):
            if s not in class_uris and s not in prop_uris:
                instances.add(s)

    lines = [
        "digraph G {",
        "  rankdir=LR;",
        '  node [style=filled, fontname="Helvetica", fontsize=11];',
        '  edge [fontname="Helvetica", fontsize=9, color="#666666"];',
    ]

    for inst in instances:
        types = list(g.objects(inst, RDF.type))
        tname = _local_name(types[0]) if types else "?"
        color = NODE_COLORS.get(tname, "#eeeeee")
        shape = "diamond" if tname in ("Measurement", "StageTransition") else "box"
        lbl = _label(g, inst).replace('"', "'")
        lines.append(f'  "{inst}" [label="{lbl}\\n({tname})", fillcolor="{color}", shape={shape}];')

    for inst in instances:
        for pred in RELATIONSHIP_PREDICATES:
            purl = MARTECH[pred]
            for o in g.objects(inst, purl):
                if o in instances:
                    lines.append(f'  "{inst}" -> "{o}" [label="{pred}"];')
                elif isinstance(o, rdflib.URIRef):
                    ext_label = _local_name(o)
                    lines.append(f'  "{o}" [label="{ext_label}", shape=note, fillcolor="#f1f3f5", fontsize=8];')
                    lines.append(f'  "{inst}" -> "{o}" [label="{pred}", style=dashed];')

    lines.append("}")
    return "\n".join(lines)


def render_graph(dot_source, dot_path=OUTPUT_DOT, png_path=OUTPUT_PNG):
    """Write the DOT file and render it to PNG via the `dot` command."""
    with open(dot_path, "w") as f:
        f.write(dot_source)
    subprocess.run(["dot", "-Tpng", dot_path, "-o", png_path], check=True)
    print(f"\nRendered {png_path}")


def print_component_context(g):
    """
    The rendered diagram deliberately omits literal properties (definition,
    caveats, context, owner) to stay readable -- this prints them as a
    companion table so the business meaning isn't lost, just shown
    differently.
    """
    query = """
    PREFIX martech: <https://example.org/martech/ontology/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?label ?definition ?caveats ?owner WHERE {
      ?comp a martech:Component ; rdfs:label ?label .
      OPTIONAL { ?comp martech:definition ?definition . }
      OPTIONAL { ?comp martech:caveats ?caveats . }
      OPTIONAL { ?comp martech:owner ?owner . }
    } ORDER BY ?label
    """
    print("\n--- Component business context (not shown in the diagram) ---")
    for row in g.query(query):
        print(f"\n{row.label}  (owner: {row.owner or '—'})")
        print(f"  definition: {row.definition or '—'}")
        print(f"  caveats:    {row.caveats or '—'}")


def extract_explorer_data(g):
    """
    Query the live graph for everything the HTML explorer needs: every
    journey's stages in order (with the component + filter_value behind
    each), and every component's business context. Auto-generalizes to
    any number of journeys -- nothing here is hardcoded to a specific one.
    """
    journeys_q = """
    PREFIX martech: <https://example.org/martech/ontology/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?journeyLabel ?order ?stageLabel ?compLabel ?filterValue WHERE {
      ?journey a martech:Journey ; rdfs:label ?journeyLabel ; martech:has_stage ?stage .
      ?stage martech:order ?order ; rdfs:label ?stageLabel .
      ?m martech:measured_entity ?stage ; martech:measured_component ?comp .
      ?comp rdfs:label ?compLabel .
      OPTIONAL { ?m martech:filter_value ?filterValue . }
    } ORDER BY ?journeyLabel ?order
    """
    journeys = {}
    for row in g.query(journeys_q):
        j = str(row.journeyLabel)
        journeys.setdefault(j, []).append({
            "stage": str(row.stageLabel),
            "component": str(row.compLabel),
            "filter_value": str(row.filterValue) if row.filterValue else None,
        })

    components = {}
    for s in g.subjects(RDF.type, MARTECH.Component):
        label = str(g.value(s, RDFS.label))
        components[label] = {
            "definition": str(g.value(s, MARTECH.definition) or "—"),
            "caveats": str(g.value(s, MARTECH.caveats) or "—"),
            "context": str(g.value(s, MARTECH.context) or "—"),
            "owner": str(g.value(s, MARTECH.owner) or "—"),
            "type": str(g.value(s, MARTECH.component_type) or "—"),
            "refs": str(g.value(s, MARTECH.refs) or "—"),
        }

    return {
        "journeys": [{"name": name, "stages": stages} for name, stages in journeys.items()],
        "components": components,
    }


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Martech knowledge graph explorer</title>
<style>
  :root {
    --bg: #ffffff; --surface: #f4f3f0; --text: #1a1a18; --text-secondary: #63615a;
    --text-muted: #8a8880; --border: #e4e2db; --accent-bg: #eaf3fb; --accent-text: #1a5a96;
    --warn-text: #8a5a10;
  }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    background: var(--bg); color: var(--text); max-width: 760px; margin: 40px auto; padding: 0 20px;
  }
  h1 { font-size: 20px; font-weight: 500; margin: 0 0 4px; }
  p.sub { color: var(--text-secondary); font-size: 14px; margin: 0 0 28px; }
  .journey-label { font-size: 13px; color: var(--text-secondary); margin: 0 0 8px; }
  .journey-row { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-bottom: 20px; }
  .stage-btn {
    background: var(--surface); border: none; border-radius: 8px; padding: 8px 14px;
    font-size: 13px; cursor: pointer; color: var(--text); font-family: inherit;
  }
  .stage-btn:hover { background: var(--accent-bg); color: var(--accent-text); }
  .arrow { color: var(--text-muted); font-size: 14px; }
  #panel {
    margin-top: 12px; background: var(--surface); border-radius: 8px;
    padding: 16px 20px; min-height: 100px;
  }
  #panel-empty { color: var(--text-muted); font-size: 14px; margin: 0; }
  .panel-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
  #panel-title { font-weight: 500; font-size: 16px; margin: 0; }
  #panel-owner {
    font-size: 12px; color: var(--accent-text); background: var(--accent-bg);
    padding: 2px 10px; border-radius: 6px; white-space: nowrap;
  }
  #panel-filter { font-size: 12px; color: var(--text-secondary); margin: 0 0 10px; }
  #panel-def { font-size: 14px; margin: 0 0 10px; line-height: 1.6; }
  .caveat-wrap { display: flex; gap: 8px; margin-bottom: 10px; }
  .caveat-icon { color: var(--warn-text); flex-shrink: 0; }
  #panel-caveat { font-size: 13px; color: var(--text-secondary); margin: 0; line-height: 1.6; }
  #panel-context { font-size: 13px; color: var(--text-secondary); margin: 0 0 10px; line-height: 1.6; }
  #panel-refs { font-size: 12px; color: var(--text-muted); margin: 0; font-family: monospace; word-break: break-all; }
</style>
</head>
<body>

<h1>Martech knowledge graph explorer</h1>
<p class="sub">Generated from martech-ontology.ttl + *-instances.ttl. Hover or click a stage to see the business context behind it.</p>

<div id="journeys"></div>

<div id="panel">
  <p id="panel-empty">Hover or click a stage above to see the component behind it.</p>
  <div id="panel-content" style="display: none;">
    <div class="panel-header">
      <p id="panel-title"></p>
      <span id="panel-owner"></span>
    </div>
    <p id="panel-filter"></p>
    <p id="panel-def"></p>
    <div class="caveat-wrap">
      <span class="caveat-icon">&#9888;</span>
      <p id="panel-caveat"></p>
    </div>
    <p id="panel-context"></p>
    <p id="panel-refs"></p>
  </div>
</div>

<script>
const DATA = __DATA_JSON__;

const container = document.getElementById("journeys");
DATA.journeys.forEach(j => {
  const section = document.createElement("div");

  const label = document.createElement("p");
  label.className = "journey-label";
  label.textContent = j.name;
  section.appendChild(label);

  const row = document.createElement("div");
  row.className = "journey-row";

  j.stages.forEach((s, i) => {
    const btn = document.createElement("button");
    btn.className = "stage-btn";
    btn.textContent = s.stage;
    btn.addEventListener("mouseenter", () => showComponent(s.component, s.filter_value));
    btn.addEventListener("click", () => showComponent(s.component, s.filter_value));
    row.appendChild(btn);

    if (i < j.stages.length - 1) {
      const arrow = document.createElement("span");
      arrow.className = "arrow";
      arrow.textContent = "\\u2192";
      row.appendChild(arrow);
    }
  });

  section.appendChild(row);
  container.appendChild(section);
});

function showComponent(name, filterValue) {
  const c = DATA.components[name];
  if (!c) return;
  document.getElementById("panel-empty").style.display = "none";
  document.getElementById("panel-content").style.display = "block";
  document.getElementById("panel-title").textContent = name + " (" + c.type + ")";
  document.getElementById("panel-owner").textContent = c.owner;
  document.getElementById("panel-filter").textContent = filterValue ? "Filtered to: " + filterValue : "";
  document.getElementById("panel-def").textContent = c.definition;
  document.getElementById("panel-caveat").textContent = c.caveats;
  document.getElementById("panel-context").textContent = c.context;
  document.getElementById("panel-refs").textContent = c.refs;
}
</script>
</body>
</html>
"""


def render_html_explorer(g, path=OUTPUT_HTML):
    """Extract graph data and write a standalone, self-contained HTML file."""
    data = extract_explorer_data(g)
    html = HTML_TEMPLATE.replace("__DATA_JSON__", json.dumps(data))
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {path}")


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


GRAPH_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Martech knowledge graph — network view</title>
<script src="node_modules/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  :root {
    --bg: #ffffff; --surface: #f4f3f0; --text: #1a1a18; --text-secondary: #63615a;
    --text-muted: #8a8880; --border: #e4e2db; --accent-bg: #eaf3fb; --accent-text: #1a5a96;
  }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    background: var(--bg); color: var(--text); max-width: 1100px; margin: 30px auto; padding: 0 20px;
  }
  h1 { font-size: 20px; font-weight: 500; margin: 0 0 4px; }
  p.sub { color: var(--text-secondary); font-size: 14px; margin: 0 0 16px; }
  #legend { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 12px; }
  .legend-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-secondary); }
  .swatch { width: 10px; height: 10px; border-radius: 3px; }
  #layout { display: flex; gap: 16px; }
  #network-canvas { flex: 1; height: 560px; background: var(--surface); border-radius: 8px; }
  #panel {
    width: 280px; flex-shrink: 0; background: var(--surface); border-radius: 8px;
    padding: 16px; height: 560px; overflow-y: auto;
  }
  #panel-empty { color: var(--text-muted); font-size: 14px; margin: 0; }
  #panel-title { font-weight: 500; font-size: 15px; margin: 0 0 2px; }
  #panel-type {
    font-size: 11px; color: var(--accent-text); background: var(--accent-bg);
    padding: 2px 8px; border-radius: 6px; display: inline-block; margin-bottom: 12px;
  }
  .prop-row { margin-bottom: 10px; }
  .prop-key { font-size: 11px; color: var(--text-muted); text-transform: uppercase; margin: 0 0 2px; letter-spacing: 0.03em; }
  .prop-val { font-size: 13px; margin: 0; line-height: 1.5; word-break: break-word; }
</style>
</head>
<body>

<h1>Martech knowledge graph — network view</h1>
<p class="sub">Drag nodes, scroll to zoom, click a node for its full properties, hover an edge for the relationship name.</p>
<div id="legend"></div>

<div id="layout">
  <div id="network-canvas"></div>
  <div id="panel">
    <p id="panel-empty">Click a node to see its properties.</p>
    <div id="panel-content" style="display: none;">
      <p id="panel-title"></p>
      <span id="panel-type"></span>
      <div id="panel-props"></div>
    </div>
  </div>
</div>

<script>
const DATA = __DATA_JSON__;

const GROUP_COLORS = {
  Requirement: "#F0997B", KPI: "#5DCAA5", Journey: "#EF9F27", Stage: "#F0997B",
  Feature: "#AFA9EC", Component: "#7F77DD", DataLayerVariable: "#ED93B1",
  Measurement: "#B4B2A9", StageTransition: "#B4B2A9"
};

const groups = [];
DATA.nodes.forEach(n => { if (groups.indexOf(n.group) === -1) groups.push(n.group); });
const legendEl = document.getElementById("legend");
groups.forEach(gr => {
  const item = document.createElement("div");
  item.className = "legend-item";
  const sw = document.createElement("span");
  sw.className = "swatch";
  sw.style.background = GROUP_COLORS[gr] || "#B4B2A9";
  item.appendChild(sw);
  const txt = document.createElement("span");
  txt.textContent = gr;
  item.appendChild(txt);
  legendEl.appendChild(item);
});

const visNodes = new vis.DataSet(DATA.nodes.map(n => ({
  id: n.id,
  label: n.label,
  title: n.group,
  color: { background: GROUP_COLORS[n.group] || "#B4B2A9", border: "#ffffff" },
  shape: (n.group === "Measurement" || n.group === "StageTransition") ? "diamond" : "box",
  font: { size: 13, color: "#1a1a18" },
})));

const visEdges = new vis.DataSet(DATA.edges.map((e, i) => ({
  id: i,
  from: e.from,
  to: e.to,
  arrows: "to",
  title: e.label,
  color: { color: "#c4c2b8" },
  width: 1,
})));

const network = new vis.Network(
  document.getElementById("network-canvas"),
  { nodes: visNodes, edges: visEdges },
  {
    physics: { stabilization: true, barnesHut: { springLength: 120 } },
    interaction: { hover: true },
    edges: { smooth: { type: "continuous" } },
  }
);

network.once("stabilizationIterationsDone", () => {
  network.setOptions({ physics: false });
  network.fit({ animation: false });
});

const dataById = {};
DATA.nodes.forEach(n => { dataById[n.id] = n; });

network.on("click", params => {
  if (params.nodes.length === 0) return;
  const n = dataById[params.nodes[0]];
  document.getElementById("panel-empty").style.display = "none";
  document.getElementById("panel-content").style.display = "block";
  document.getElementById("panel-title").textContent = n.label;
  document.getElementById("panel-type").textContent = n.group;
  const propsDiv = document.getElementById("panel-props");
  propsDiv.innerHTML = "";
  Object.entries(n.properties).forEach(([key, val]) => {
    const row = document.createElement("div");
    row.className = "prop-row";
    const k = document.createElement("p");
    k.className = "prop-key";
    k.textContent = key;
    const v = document.createElement("p");
    v.className = "prop-val";
    v.textContent = val;
    row.appendChild(k);
    row.appendChild(v);
    propsDiv.appendChild(row);
  });
});
</script>
</body>
</html>
"""


def render_html_graph(g, path=OUTPUT_GRAPH_HTML):
    """Extract the full instance graph and write a standalone, clickable network view."""
    data = extract_full_graph(g)
    html = GRAPH_HTML_TEMPLATE.replace("__DATA_JSON__", json.dumps(data))
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {path} ({len(data['nodes'])} nodes, {len(data['edges'])} edges)")


def main():
    g = load_graph()
    print(f"Loaded graph: {len(g)} triples")

    run_sample_query(g)
    print_component_context(g)

    dot_source = build_dot(g)
    render_graph(dot_source)

    render_html_explorer(g)
    render_html_graph(g)


if __name__ == "__main__":
    main()
