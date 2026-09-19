# Unified Martech Knowledge Graph (MVP)

A small, working example of a knowledge graph for martech data — built as an RDFS ontology in Turtle, queried with SPARQL, and visualized two ways (static + interactive). This is the companion code for a blog series on modeling business meaning (journeys, KPIs, requirements) alongside technical metadata (XDM components, data layer variables) as one connected graph.

All data in this repo is generic example content (Adobe Experience Platform's public Champion sandbox) — not tied to any specific company.

## What's in here

| Path | What it is |
|---|---|
| `pyproject.toml` | Package definition — `pip install .` (or `pip install -e .` for local dev) installs the `martech-knowledge-graph` command |
| `src/martech_knowledge_graph/ontology/martech-ontology.ttl` | The schema: node classes (`Requirement`, `KPI`, `Journey`, `Stage`, `Feature`, `Component`, `DataLayerVariable`) and the predicates connecting them |
| `src/martech_knowledge_graph/examples/*.ttl` | Bundled example journey data (a 4-step ecommerce funnel, a 2-step login flow) — loadable on demand via the UI's "Load demo data" button, never forced on a fresh install |
| `src/martech_knowledge_graph/graph_explorer.py` | Loads the ontology + instance turtle files, runs a sample SPARQL query, and generates a static PNG plus two standalone HTML visualizations |
| `src/martech_knowledge_graph/query_graph.py` | A lighter-weight companion — four standalone sample SPARQL queries, no visualization, a good starting point for writing your own |
| `src/martech_knowledge_graph/journey_builder.py` | Generates correct turtle from structured input (a spreadsheet or Python), instead of hand-writing it |
| `src/martech_knowledge_graph/server.py` + `cli.py` | The local API + UI server behind the `martech-knowledge-graph serve` command |
| `src/martech_knowledge_graph/ui/` | The maintenance UI (components, journeys, graph viewer, SPARQL query, ontology reference) — served by `server.py`, see [Web UI](#web-ui) below |

## Setup

Requires Python 3.9+.
```
git clone <this-repo-url>
cd martech-knowledge-graph
python -m venv .venv
```
Activate it (`.venv\Scripts\Activate.ps1` on Windows PowerShell, `source .venv/bin/activate` on Mac/Linux), then:
```
pip install -e .
```
This installs `rdflib` and `flask` (the only two dependencies) and adds a `martech-knowledge-graph` command
to your environment. To install it elsewhere (e.g. someone else's machine) without cloning first:
```
pip install git+<this-repo-url>
```

**Graphviz** (only needed for `graph_explorer.py`'s standalone static PNG output — not needed for the web UI)

Graphviz is a separate system program, not a Python package — `pip` can't install it. Steps below are more detailed than usual, since getting it onto your system PATH is the step most likely to trip you up.

*Windows:*
1. Open PowerShell and run:
   ```
   winget install graphviz
   ```
   (winget is Windows' built-in package manager, included on Windows 10/11. If it's not available, download the installer directly from https://graphviz.org/download/ instead.)
2. Fully close and reopen your terminal (and VS Code, if you're using it) — PATH changes don't apply to already-open windows.
3. Verify it worked:
   ```
   dot -V
   ```
   This should print something like `dot - graphviz version 12.x.x`.
4. **If step 3 says "not recognized"** — this is common, since some install methods don't add Graphviz to PATH automatically. First confirm it's actually installed and find where:
   ```
   Test-Path "C:\Program Files\Graphviz\bin\dot.exe"
   ```
   If that returns `True`, add it to PATH manually:
   - Search Windows for "environment variables" → open "Edit the system environment variables"
   - Click "Environment Variables..."
   - Under "System variables" (or "User variables" if you don't have admin rights), select `Path` → "Edit..." → "New"
   - Paste: `C:\Program Files\Graphviz\bin`
   - OK on all open dialogs, then fully close and reopen your terminal again
   - Run `dot -V` once more to confirm

*Mac:*
```
brew install graphviz
```

*Linux:*
```
apt install graphviz
```

## Usage

```
martech-knowledge-graph serve
```

Then open **http://127.0.0.1:5055/** — this is the primary way to use this project (see
[Web UI](#web-ui) below). A fresh install starts with an empty data directory; click **Load demo data**
on the home page to populate it with the two example journeys.

Options:
```
martech-knowledge-graph serve --data-dir ./my-data --host 127.0.0.1 --port 8080
```
- `--data-dir` (default `./martech-knowledge-graph-data`, created automatically) — where your own
  `*-instances.ttl` files live, kept separate from the bundled ontology and example data so a `git pull`
  or reinstall never touches your content.
- `--host` / `--port` (defaults `127.0.0.1` / `5055`).
- `--debug` — enables Flask's debugger. Off by default; only pass this for local development, since the
  debugger allows arbitrary code execution if the port is ever reachable by anyone else.

**`graph_explorer.py`** also still works as a standalone script, separately from the web UI, for a static
PNG export or the older two-file HTML visualization — against the bundled example data by default:
```
python -m martech_knowledge_graph.graph_explorer
```
This loads the ontology + bundled examples and produces (in your current directory):
- Console output — a sample query plus each component's business context (definition, caveats, owner)
- `graph.png` — static diagram (needs Graphviz, below)
- `explorer.html` — journey-focused view: click through stages, see the component behind each one
- `graph_network.html` — the full graph as a draggable, zoomable network (needs `npm install vis-network`
  run from wherever you invoke this — see the module's own docstring; this is independent of the web UI,
  which already bundles vis-network and needs none of this)

**`query_graph.py`** — no visualization, just four sample SPARQL queries against the bundled example
data, printed to the console:
```
python -m martech_knowledge_graph.query_graph
```
A good starting point for writing your own queries before moving to the web UI's Query page.

## Web UI

The web UI covers the whole loop: pull components, curate their business context, author journeys,
browse the graph, and run SPARQL against it — plus an ontology reference and a page listing the raw data
files. `martech-knowledge-graph serve` serves it directly at `http://127.0.0.1:5055/`; every page also
still works opened as a standalone file (e.g. if you only copied `src/martech_knowledge_graph/ui/`
somewhere), falling back to static example data when the API isn't reachable. See `ui/WIRING.md` for
exactly what's wired to what.

## Adding a new journey

You don't need to hand-write turtle. Three ways in — the first two produce identical output (verified
byte-for-byte):

**Web UI (recommended)** — paste or upload a CSV on the Journeys page (`martech-knowledge-graph serve`,
then `/journeys.html`) and click Generate turtle. This runs the same builder below and writes the result
straight into your data directory.

**Spreadsheet, scripted** — one row per stage; Journey/Requirement/KPI/data-layer columns repeat the same
value on every row; each unique `component_key` only needs its definition/caveats/context filled in once
even if several stages share it. `journey_builder.write_csv_template(path)` writes an empty template with
the right headers to start from. Then:
```python
from martech_knowledge_graph.journey_builder import build_journey_from_csv

with open("my-journey-instances.ttl", "w") as f:
    f.write(build_journey_from_csv("my-journey.csv"))
```

**Python**, if you prefer — build a `JourneySpec` directly (see `build_example_ecommerce()` / `build_example_login()` in `journey_builder.py` for the pattern) and call `build_journey_turtle(spec)`.

If you're not going through the web UI, save the output as `<slug>-instances.ttl` in your data directory
(default `./martech-knowledge-graph-data`) — `server.py` (and `graph_explorer.py`, if pointed at that
directory) auto-discovers any file matching `*-instances.ttl`, no code changes needed.

The builder guarantees the mechanical parts are correct (the `Measurement` relation node only appears when a stage's `filter_value` is set, `DataLayerVariable.maps_to` stays in sync with which components are actually used) — it doesn't and can't decide what a Requirement says or what a Component's caveat is. That's still a judgment call, not something a script should fill in for you.

## Ontology overview

- **Requirement → KPI → Journey → Stage → Feature → Component → DataLayerVariable** is the core chain, from business question down to raw implementation.
- **`Measurement`** and **`StageTransition`** are relation nodes, not "real" entities — RDF predicates can't carry their own attributes (like a conversion rate or a filter value), so these exist specifically to hold that data. See the ontology file's comments for the full reasoning.
- Every `Component` carries business meaning (`definition`, `caveats`, `context`, `owner`) directly on the node — the thing a platform's own technical metadata graph (e.g. Adobe's native schema/catalog graph) structurally can't hold, since there's no such thing as a "business meaning" field on a raw schema object.

## Status

- ✅ Ontology, two example journeys, querying, and both visualizations — working, validated.
- ✅ Structured authoring (spreadsheet or Python) for adding new journeys without hand-writing turtle — working, validated against the two existing journeys.
- ✅ Web UI + local API (`martech-knowledge-graph serve`) — real persistence to the `.ttl` files, not just a demo: component context edits, CJA sync (simulated auth, real writes), and journey generation all round-trip through the actual data directory; the graph viewer and SPARQL query page read that same live state.
- ✅ Installable as a package (`pip install git+<this-repo-url>` or `pip install -e .` from a clone) — no PyPI publish yet, git/local install only.
- ⏳ Not yet built: exposing this graph through an MCP server so an LLM/agent can query it, and testing whether it actually improves answer quality. Planned as a later addition.
- ⏳ Not yet built: validation rules (e.g. SHACL) enforcing the ontology's constraints automatically, regardless of how a change was authored.
- ⏳ Not yet built: a way for a journey's CSV to reference an already-curated component by key instead of re-entering its definition/caveats/context inline on every stage row.

## License

MIT — see `LICENSE`.