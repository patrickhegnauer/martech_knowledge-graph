---
name: martech-knowledge-graph
description: Use when answering questions about this organization's martech metrics/dimensions (CJA components), their business definitions/caveats/owners, customer journeys, KPIs, or business requirements. Trigger on questions like "what does this metric mean", "what's the caveat on this dimension", "which journeys use this component", "what KPI does this tie back to", or anything asking for curated business context that CJA's own technical metadata doesn't hold. Requires an MCP connection to a running `martech-knowledge-graph mcp` server.
---

# Martech Knowledge Graph

A knowledge graph connecting business requirements down to raw implementation:
**Requirement → KPI → Journey → Stage → Feature → Component → DataLayerVariable**. `Component` is a
metric or dimension from the CJA Semantic Layer — its identity is authoritative in CJA/AEP, but its
**business meaning** (`definition`, `caveats`, `context`, `owner`) is curated here, on the graph, because
that's a field CJA's own technical metadata has no place for. Flat RDF/Turtle files, no database, served
by a small local Flask app plus a separate MCP server — see this repo's `README.md` for the full
architecture if you need it; you don't need it to use this skill.

## Connecting

The graph is exposed over MCP (Streamable HTTP) by:
```
martech-knowledge-graph mcp
```
which prints the URL it's listening on — `http://127.0.0.1:8931/mcp` by default. Add that as an MCP
server connection. There's no authentication (localhost-only by default) — if you can't reach it, it
probably isn't running; ask the person you're helping to start it (`martech-knowledge-graph mcp` in a
terminal, from wherever this repo/package is installed) rather than guessing at data.

Two tools are exposed, nothing else (deliberately -- one query doorway, not many competing ones):

## `get_ontology_schema()`

Returns every class and property in the ontology — name, comment, and (for properties) domain/range.
**Call this first** if you don't already know the graph's shape, or if a `run_sparql` query comes back
empty/wrong and you're not sure why. The answer is generated live from the actual ontology file, so trust
it over anything you remember from a previous session — the ontology can change between conversations.

Don't assume the class/property list below is exhaustive or current; it's orientation, not a substitute
for calling the tool. As of when this skill was written, the core shape was:

- **Classes**: `Requirement`, `KPI`, `Journey`, `Stage`, `Feature`, `Component`, `DataLayerVariable`,
  `StageTransition`, `Measurement`.
- **`Measurement`** and **`StageTransition`** aren't "real" business entities — they're n-ary relation
  nodes that exist only because a plain RDF predicate can't carry its own attribute (a `Measurement`
  carries an optional `filter_value`; a `StageTransition` carries a `conversion_rate`). To find what
  component measures a stage, go `Stage <- measured_entity - Measurement - measured_component -> Component`.
- **Key `Component` properties**: `definition` (plain-language meaning), `caveats` (known data-quality
  issues — always check this before quoting a number), `context` (why it matters), `owner`,
  `component_type` (`"metric"` or `"dimension"`), `refs` (a pointer to the component's authoritative
  entity in CJA/AEP's own graph — a reference only, don't treat it as content).
- Namespace: `https://example.org/martech/ontology/` (prefix `martech:` in examples below) — this is a
  placeholder base URI in the public template; a real org deployment may have swapped in their own.
  `get_ontology_schema()` tells you the truth regardless.

## `run_sparql(query)`

Runs a **read-only** SPARQL query (`SELECT`, `ASK`, `CONSTRUCT`, or `DESCRIBE`) against the graph.
`INSERT`/`DELETE` aren't supported — don't attempt them, they will fail. This tool only ever reads; it
is not how business context gets added or corrected (that happens through the web UI, by a human who owns
that judgment call — see `README.md`'s "Adding a new journey" / component-editing flow if someone asks
how to change something here).

**Response shape**: `{"results": [...]}` for `SELECT`/`CONSTRUCT`/`DESCRIBE` (a list of dicts — variable
bindings for `SELECT`, `{subject, predicate, object}` triples for `CONSTRUCT`/`DESCRIBE`),
`{"result": true|false}` for `ASK`, or `{"error": "..."}` if the query didn't parse or run. Always check
for the `error` key before assuming you got data.

Standard prefixes to use:
```sparql
PREFIX martech: <https://example.org/martech/ontology/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
```

### Example: business context for every component

The question you'll get asked most often — "what does this metric/dimension actually mean, and what
should I watch out for":
```sparql
SELECT ?label ?definition ?caveats ?owner WHERE {
  ?comp a martech:Component ; rdfs:label ?label .
  OPTIONAL { ?comp martech:definition ?definition . }
  OPTIONAL { ?comp martech:caveats ?caveats . }
  OPTIONAL { ?comp martech:owner ?owner . }
} ORDER BY ?label
```
Filter with `FILTER(CONTAINS(LCASE(?label), "checkout"))` (or similar) if you're after one specific
component rather than everything.

### Example: walk a funnel (stage → component → CJA reference)

```sparql
SELECT ?order ?stageLabel ?componentLabel ?ref WHERE {
  ?stage a martech:Stage ; martech:order ?order ; rdfs:label ?stageLabel .
  ?m a martech:Measurement ;
     martech:measured_entity ?stage ;
     martech:measured_component ?comp .
  ?comp rdfs:label ?componentLabel ; martech:refs ?ref .
} ORDER BY ?order
```

### Example: every journey's stages, in order, with a filter value where one applies

Useful when a component is shared across stages (e.g. one `page_name` dimension identifying several
different steps by its value) — the `filter_value` is what actually distinguishes them:
```sparql
SELECT ?journeyLabel ?order ?stageLabel ?compLabel ?filterValue WHERE {
  ?journey a martech:Journey ; rdfs:label ?journeyLabel ; martech:has_stage ?stage .
  ?stage martech:order ?order ; rdfs:label ?stageLabel .
  ?m martech:measured_entity ?stage ; martech:measured_component ?comp .
  ?comp rdfs:label ?compLabel .
  OPTIONAL { ?m martech:filter_value ?filterValue . }
} ORDER BY ?journeyLabel ?order
```

## Things to get right

- **Always surface `caveats`, not just `definition`**, when explaining a metric to someone who might act
  on it — that field exists specifically because the raw number is easy to misread (e.g. "counts page
  views, not unique visitors" on a component literally named `product_views`).
- **`refs` is a pointer, not a duplicate.** If asked what a component *is* technically (its real CJA/XDM
  identity), say the `refs` value points to that in CJA/AEP's own graph — don't invent or assume details
  about it beyond what's there.
- **This may be demo data.** A fresh install of this tool defaults to a bundled demo workspace with two
  illustrative example journeys (an ecommerce funnel, a login flow) — not necessarily this org's real
  data. If answers look generic/example-shaped (owners like "Digital Analytics", obviously placeholder
  URLs), say so rather than presenting them as the org's real configuration, and suggest checking whether
  the server is in demo or org mode.
- **No result isn't always "doesn't exist."** A `SELECT` with zero rows can mean the component genuinely
  isn't curated yet (real gap — a component pulled from CJA but nobody's written its business context)
  rather than a query mistake. Consider both before concluding either way.
