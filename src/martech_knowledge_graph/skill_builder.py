"""Generates a data-grounded starting draft for an AI agent's skill file.

Split deliberately: the schema and example queries below are mechanical facts, always safe to regenerate
from the live graph (same principle as component context vs. generated turtle elsewhere in this app). The
closing "Things to get right" section is a human/LLM-curated starting point -- no generator can know an
org's real gotchas, only its current shape and content.
"""

from . import graph_explorer as ge

RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"

# (title, optional note, SPARQL body -- PREFIX lines are added when run/rendered)
EXAMPLE_QUERIES = [
    (
        "Business context for every component",
        "The question you'll get asked most often -- what does this metric/dimension actually mean, and "
        "what should you watch out for:",
        "SELECT ?label ?definition ?caveats ?owner WHERE {\n"
        "  ?comp a martech:Component ; rdfs:label ?label .\n"
        "  OPTIONAL { ?comp martech:definition ?definition . }\n"
        "  OPTIONAL { ?comp martech:caveats ?caveats . }\n"
        "  OPTIONAL { ?comp martech:owner ?owner . }\n"
        "} ORDER BY ?label",
    ),
    (
        "Walk a funnel (stage -> component -> reference)",
        None,
        "SELECT ?order ?stageLabel ?componentLabel ?ref WHERE {\n"
        "  ?stage a martech:Stage ; martech:order ?order ; rdfs:label ?stageLabel .\n"
        "  ?m a martech:Measurement ;\n"
        "     martech:measured_entity ?stage ;\n"
        "     martech:measured_component ?comp .\n"
        "  ?comp rdfs:label ?componentLabel ; martech:refs ?ref .\n"
        "} ORDER BY ?order",
    ),
    (
        "Every journey's stages, in order, with a filter value where one applies",
        "Useful when a component is shared across stages (e.g. one dimension identifying several steps "
        "by its value) -- the filter value is what actually distinguishes them:",
        "SELECT ?journeyLabel ?order ?stageLabel ?compLabel ?filterValue WHERE {\n"
        "  ?journey a martech:Journey ; rdfs:label ?journeyLabel ; martech:has_stage ?stage .\n"
        "  ?stage martech:order ?order ; rdfs:label ?stageLabel .\n"
        "  ?m martech:measured_entity ?stage ; martech:measured_component ?comp .\n"
        "  ?comp rdfs:label ?compLabel .\n"
        "  OPTIONAL { ?m martech:filter_value ?filterValue . }\n"
        "} ORDER BY ?journeyLabel ?order",
    ),
    (
        "Which data layer variable feeds a component",
        "DataLayerVariable is the raw implementation artifact; maps_to links it to the component it "
        "populates (a component can have several, and one variable can feed several components):",
        "SELECT ?componentLabel ?variable ?sourceSystem WHERE {\n"
        "  ?dlv a martech:DataLayerVariable ; rdfs:label ?variable ; martech:maps_to ?comp .\n"
        "  ?comp rdfs:label ?componentLabel .\n"
        "  OPTIONAL { ?dlv martech:source_system ?sourceSystem . }\n"
        "} ORDER BY ?componentLabel",
    ),
]

_KEY_PROPERTIES = [
    ("definition", "plain-language meaning"),
    ("caveats", "known data-quality issues"),
    ("context", "why it matters"),
    ("owner", "who's responsible"),
    ("component_type", '"metric" or "dimension"'),
    ("refs", "pointer to the CJA/XDM source, not a duplicate"),
    ("is_pii", "whether it carries or is derived from personally identifiable information"),
    ("governance_notes", "consent, retention, or other compliance-relevant notes"),
]


def _render_query_block(title, note, query, g):
    prefixes = f"PREFIX martech: <{ge.MARTECH}>\nPREFIX rdfs: <{RDFS_NS}>\n\n"
    try:
        rows = len(list(g.query(prefixes + query)))
        plural = "s" if rows != 1 else ""
        row_note = (
            f"Returns **{rows} row{plural}** in this graph right now."
            if rows else "Returns **0 rows** right now -- nothing matching yet, not necessarily a broken query."
        )
    except Exception as exc:
        row_note = f"Could not run this against the current graph ({type(exc).__name__}) -- check it still matches your ontology."

    lines = [f"### {title}", ""]
    if note:
        lines += [note, ""]
    lines += ["```sparql", query, "```", row_note, ""]
    return "\n".join(lines)


def build_skill_draft(g, name):
    """Returns the full markdown content of a skill draft grounded in `g` (an already-loaded rdflib.Graph)."""
    schema = ge.extract_ontology_schema(g)
    classes = ", ".join(f"`{c['name']}`" for c in schema["classes"])
    comments = {p["name"]: p["comment"] for p in schema["properties"]}

    key_props = "\n".join(
        f"  - **`{prop}`** ({label}): {comments[prop]}" if comments.get(prop) else f"  - **`{prop}`** ({label})"
        for prop, label in _KEY_PROPERTIES if prop in comments
    )
    query_blocks = "\n".join(_render_query_block(t, n, q, g) for t, n, q in EXAMPLE_QUERIES)

    return f"""---
name: {name}
description: Use when answering questions about this organization's martech metrics/dimensions, their
  business definitions/caveats/owners, customer journeys, KPIs, or business requirements -- refine this
  trigger description once you know the real questions people ask.
---

# {name}

Draft generated by `martech-knowledge-graph` from the graph as it is right now -- the schema and example
queries below are live facts; the "Things to get right" section at the end is a starting point you (or
your own LLM) should finish with your organization's real gotchas. Regenerating overwrites everything
above that section, never that section itself automatically -- review before overwriting a hand-edited file.

## Connecting

```
martech-knowledge-graph mcp
```
prints the URL it listens on (`http://127.0.0.1:8931/mcp` by default over Streamable HTTP). Other
transports: `--transport stdio` for Claude Desktop's local server config, or a hosted URL via
`martech-knowledge-graph export-mcp` (deploy to your own Prefect Horizon). No authentication on the local
server -- if you can't reach it, it probably isn't running.

Two tools, nothing else: `get_ontology_schema()` (call first if unsure of the shape) and `run_sparql(query)`
(read-only SELECT/ASK/CONSTRUCT/DESCRIBE; INSERT/DELETE fail to parse, by design).

## Ontology overview

- **Classes**: {classes}
- **Key `Component` properties**:
{key_props}
- **Namespace**: `{ge.MARTECH}` (prefix `martech:` below)

## Example queries

{query_blocks}
## Things to get right

*(Starting point -- edit this for your organization's real gotchas.)*

- **Always surface `caveats`, not just `definition`**, when explaining a metric to someone who might act
  on it.
- **`refs` is a pointer, not a duplicate.** Don't invent or assume details about a component's CJA/XDM
  identity beyond what's there.
- **No result isn't always "doesn't exist."** A zero-row `SELECT` can mean genuinely uncurated, not a
  query mistake.
- <!-- TODO: add what you actually keep getting asked, known-bad data, deprecated components, seasonal
  metrics, who owns what -- the things a new team member would need told to them once. -->
"""
