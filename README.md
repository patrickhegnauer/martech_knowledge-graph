# Unified Martech Knowledge Graph (MVP)

A small, working example of a knowledge graph for martech data — built as an RDFS ontology in Turtle, served through a web UI with a live interactive graph view and a SPARQL query page. This is the companion code for a blog series on modeling business meaning (journeys, KPIs, requirements) alongside technical metadata (XDM components, data layer variables) as one connected graph.

All data in this repo is generic example content (Adobe Experience Platform's public Champion sandbox) — not tied to any specific company.

## Architecture

No database, no build step — flat `.ttl` files are the storage layer, read and written directly by a
small Flask app that also serves the UI itself:

```mermaid
flowchart LR
    Browser["Browser<br/>ui/*.html + mode-banner.js"]

    subgraph Server["martech-knowledge-graph serve (Flask)"]
        API["/api/* JSON endpoints<br/>+ static ui/ files"]
        GE["graph_explorer.py<br/>(load + extract)"]
        JB["journey_builder.py<br/>(CSV/Python → turtle)"]
    end

    subgraph Data["Flat .ttl files — no database"]
        ONT["ontology/martech-ontology.ttl<br/>always loaded, read-only"]
        DEMO["examples/*.ttl<br/>demo workspace, read-only"]
        ORG["--data-dir<br/>org workspace, read/write<br/>+ .mkg-mode + .mkg-settings.json"]
    end

    Browser <-->|"fetch()"| API
    API --> GE
    API --> JB
    GE --> ONT
    GE -. demo mode .-> DEMO
    GE -. org mode .-> ORG
    JB -->|writes generated journeys| ORG
```

The demo/org mode switch (top right of every page) changes which of `examples/` or `--data-dir` the
server reads and writes on every request — see [Web UI](#web-ui) below. `ui/WIRING.md` has the detailed,
page-by-page version of this diagram: every element ID, every endpoint, and exactly what's wired to what.

## What's in here

| Path | What it is |
|---|---|
| `pyproject.toml` | Package definition — `pip install .` (or `pip install -e .` for local dev) installs the `martech-knowledge-graph` command |
| `src/martech_knowledge_graph/ontology/martech-ontology.ttl` | The schema: node classes (`Requirement`, `KPI`, `Journey`, `Stage`, `Feature`, `Component`, `DataLayerVariable`) and the predicates connecting them |
| `src/martech_knowledge_graph/examples/*.ttl` | Bundled example journey data (a 4-step ecommerce funnel, a 2-step login flow) — this is the **demo** workspace itself (read-only), toggled on/off with the rest of the UI's data-mode switcher, not copied anywhere |
| `src/martech_knowledge_graph/graph_explorer.py` | Internal library `server.py` uses to load the graph and extract the live graph-view data — not a standalone tool |
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

## Usage

```
martech-knowledge-graph serve
```

Then open **http://127.0.0.1:5055/** — this is the primary way to use this project (see
[Web UI](#web-ui) below). It opens in **demo mode**: the bundled example data (read-only), with a banner
on every page and a switcher in the top right. Click **Switch to your data** whenever you're ready — that
flips to your own, separate data directory (starts empty; Home turns into a live kickstart checklist for
what's left to set up). Switching is instant and non-destructive either direction; nothing is copied or
deleted, the two are genuinely separate workspaces.

Options:
```
martech-knowledge-graph serve --data-dir ./my-data --host 127.0.0.1 --port 8080
```
- `--data-dir` (default `./martech-knowledge-graph-data`, created automatically) — your **org**
  workspace: where your own `*-instances.ttl` files live once you switch out of demo mode, kept separate
  from the bundled ontology and example data so a `git pull` or reinstall never touches your content.
  Which mode is currently active is remembered in a `.mkg-mode` file inside this directory, so it
  persists across restarts. Org-specific settings (currently just the XDM base URL used for generated
  component refs — see [Journeys](#adding-a-new-journey) — set via the Journeys page) live in a
  `.mkg-settings.json` file in the same directory.
- `--host` / `--port` (defaults `127.0.0.1` / `5055`).
- `--debug` — enables Flask's debugger. Off by default; only pass this for local development, since the
  debugger allows arbitrary code execution if the port is ever reachable by anyone else.

## Web UI

The web UI covers the whole loop: pull components, curate their business context, author journeys,
browse the graph, and run SPARQL against it — plus an ontology reference and a page listing the raw data
files. `martech-knowledge-graph serve` serves it directly at `http://127.0.0.1:5055/`; every page also
still works opened as a standalone file (e.g. if you only copied `src/martech_knowledge_graph/ui/`
somewhere), falling back to static example data when the API isn't reachable. See `ui/WIRING.md` for
exactly what's wired to what.

Every page shows which workspace you're in and lets you switch (`ui/js/mode-banner.js`, the one script
included everywhere): a banner across the top in demo mode, and a "Demo data" / "Your data" switcher in
the top-right corner of the header regardless of mode. Demo mode is read-only — saving a component,
syncing from CJA, or generating a journey while still in demo mode is refused by the server with a clear
message rather than silently writing into the bundled example data.

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
(default `./martech-knowledge-graph-data`) — `server.py` auto-discovers any file matching
`*-instances.ttl` there, no code changes or restart needed.

The builder guarantees the mechanical parts are correct (the `Measurement` relation node only appears when a stage's `filter_value` is set, `DataLayerVariable.maps_to` stays in sync with which components are actually used) — it doesn't and can't decide what a Requirement says or what a Component's caveat is. That's still a judgment call, not something a script should fill in for you.

**Each component's `xdm_path` column** (e.g. `commerce.checkouts.value`) becomes its `martech:refs` URI by
appending it to a base URL — `https://sandbox/SANDBOX_NAME/xdm/` by default, a placeholder. Set your org's
real prefix once on the Journeys page (persisted to `.mkg-settings.json` in your data directory, applies
to every journey generated afterward) instead of getting a literal `SANDBOX_NAME` in every generated
file. Calling `build_journey_from_csv()`/`build_journey_turtle()` directly from Python accepts the same
thing as an `xdm_base_url` argument.

## Ontology overview

- **Requirement → KPI → Journey → Stage → Feature → Component → DataLayerVariable** is the core chain, from business question down to raw implementation.
- **`Measurement`** and **`StageTransition`** are relation nodes, not "real" entities — RDF predicates can't carry their own attributes (like a conversion rate or a filter value), so these exist specifically to hold that data. See the ontology file's comments for the full reasoning.
- Every `Component` carries business meaning (`definition`, `caveats`, `context`, `owner`) directly on the node — the thing a platform's own technical metadata graph (e.g. Adobe's native schema/catalog graph) structurally can't hold, since there's no such thing as a "business meaning" field on a raw schema object.

## Status

- ✅ Ontology, two example journeys, live graph view, and SPARQL querying — working, validated.
- ✅ Structured authoring (spreadsheet or Python) for adding new journeys without hand-writing turtle — working, validated against the two existing journeys.
- ✅ Web UI + local API (`martech-knowledge-graph serve`) — real persistence to the `.ttl` files, not just a demo: component context edits, CJA sync (simulated auth, real writes), and journey generation all round-trip through the actual data directory; the graph viewer and SPARQL query page read that same live state.
- ✅ Installable as a package (`pip install git+<this-repo-url>` or `pip install -e .` from a clone) — no PyPI publish yet, git/local install only.
- ✅ Demo/org mode switcher — every page shows which workspace is active and lets you switch between the
  bundled read-only demo data and your own data directory; Home becomes a live kickstart checklist once
  you're on your own (typically empty) data.
- ✅ Configurable XDM base URL for generated component refs — set your org's real prefix once (Journeys
  page) instead of the `SANDBOX_NAME` placeholder ending up in every generated file.
- ⏳ Not yet built: exposing this graph through an MCP server so an LLM/agent can query it, and testing whether it actually improves answer quality. Planned as a later addition.
- ⏳ Not yet built: validation rules (e.g. SHACL) enforcing the ontology's constraints automatically, regardless of how a change was authored.
- ⏳ Not yet built: a way for a journey's CSV to reference an already-curated component by key instead of re-entering its definition/caveats/context inline on every stage row.

## License

MIT — see `LICENSE`.