# Architecture and design notes

Developer reference for how the pieces fit together and why they were built that way. For the user-facing
overview and the architecture diagram, see the root `README.md`; this document goes one level deeper,
module by module and page by page.

## Contents

- [Principles](#principles)
- [Storage and workspaces](#storage-and-workspaces)
- [Ontology and form-field mapping](#ontology-and-form-field-mapping)
- [Local API (`server.py`)](#local-api-serverpy)
- [CJA sync](#cja-sync)
- [Components](#components)
- [Journeys](#journeys)
- [Shared requirement and KPI library](#shared-requirement-and-kpi-library)
- [Graph and Query pages](#graph-and-query-pages)
- [MCP server](#mcp-server)
- [Skills and the plugin marketplace](#skills-and-the-plugin-marketplace)
- [UI shell](#ui-shell)
- [Packaging and versioning](#packaging-and-versioning)
- [Known gaps](#known-gaps)
- [Troubleshooting](#troubleshooting)

## Principles

- **No database, no build step.** Storage is flat Turtle files read and written with `rdflib`. The ontology
  (`ontology/martech-ontology.ttl`) is part of the package and is never written to; only `*-instances.ttl`
  files in a workspace are.
- **Curate meaning, reference identity.** Business meaning (`definition`, `caveats`, `context`, `owner`) is
  curated here. Raw CJA/AEP metadata stays authoritative in Adobe and is only pointed at with
  `martech:refs`, never copied into the graph.
- **Don't declare what nothing populates.** Schema that no writer or instance file uses is removed rather
  than kept as scaffolding (see [Ontology](#ontology-and-form-field-mapping)). Proposed additions should
  come with whatever populates them.
- **Never silently lose curated content.** Re-syncs only add, journey edits refuse files they can't round-
  trip, and demo data can't be written to.
- **Pages degrade gracefully.** Every page still renders when opened as a plain file without the server,
  falling back to bundled example data.

## Storage and workspaces

Two workspaces, resolved per request:

| Mode | Directory | Writable |
|---|---|---|
| `demo` | the package's `examples/` folder | no |
| `org` | `--data-dir` (default `./martech-knowledge-graph-data`) | yes |

The active mode is persisted in `<data_dir>/.mkg-mode` and defaults to `demo` on a fresh install.
`workspace.py` holds the marker name and `resolve_active_dir()`, shared by both processes:

- `server.py` caches the mode in memory for the life of the Flask process and updates it when
  `POST /api/mode` writes a new one. Its `current_dir()` helper is used by every endpoint, so a switch takes
  effect immediately.
- `mcp_server.py` re-reads the marker on every tool call. It has no request loop to invalidate a cache in,
  and reading one small file is negligible. This is why a mode switch in the browser reaches an
  already-running MCP server without a restart.

Every write endpoint calls `require_org_mode()` first and returns `403` with a readable message in demo
mode, so nothing is ever written into the installed package.

Files in an org data directory:

| File | Written by | Contents |
|---|---|---|
| `components-instances.ttl` | CJA sync | Synced components not bound to a journey |
| `datalayer-instances.ttl` | Component edit page | Data layer variables and their `maps_to` links |
| `library-instances.ttl` | Journeys page, journey form | Shared requirements and KPIs |
| `<slug>-instances.ttl` | Journey form, CSV import | One journey each |
| `skills/<slug>.md` | Skills page | Generated skill drafts |
| `.mkg-mode` | Mode switcher | `demo` or `org` |
| `.mkg-settings.json` | Journeys page | `{"xdm_base_url": ...}` |
| `.mkg-cja.json` | CJA connect dialog | CJA credentials, including the client secret |
| `.mkg-cja-dataviews.json` | Data view listing, Sources page | Data view names, `{id: name}` |

Everything matching `*-instances.ttl` is loaded automatically, so a new file needs no code change.
`RESERVED_JOURNEY_SLUGS` (`components`, `datalayer`, `library`) keeps journey slugs from colliding with
the fixed files.

**Accepted trade-off:** `rdflib`'s serializer reformats any file it rewrites, so hand formatting and
comments in an instance file don't survive its first save through the API.

## Ontology and form-field mapping

Core chain: **Requirement → KPI → Journey → Stage → Component → DataLayerVariable**, plus the
`Measurement` relation node (7 classes, 21 properties). `Measurement` exists because a plain predicate
can't carry an attribute: it links a Stage to a Component and optionally holds a `filter_value`, for
example several stages that share one page-name dimension with different page paths.

Removed in a cleanup because nothing ever populated them: `Feature` / `uses_feature`, `StageTransition` /
`transition_from` / `transition_to` / `conversion_rate`, and `contributes_to`. `StageTransition` would need
real traffic numbers from CJA's Reporting API, a separate and much larger feature. A proposal for a larger
expansion (Objective/Decision, Interaction, Event, Data Element layers and extra metadata categories on
every entity) was reviewed and declined for the same reason; only the governance fields `is_pii` and
`governance_notes` were added from it.

Component edit form → ontology:

| Form field | Property | Notes |
|---|---|---|
| `definition`, `caveats`, `context` | `martech:definition` / `caveats` / `context` | Count toward context coverage, together with `owner` |
| `owner` | `martech:owner` | No fixed domain; reused on Requirement, KPI, Journey, Component |
| `is_pii` | `martech:is_pii` | Always written as an explicit boolean, so "not set" and "false" aren't conflated |
| `governance_notes` | `martech:governance_notes` | Free text. Nothing sets governance fields automatically |
| `refs` (repeatable) | `martech:refs` | Pointers to the CJA component and XDM field |
| Data layer variables (repeatable) | `DataLayerVariable` + `martech:maps_to` | Stored in `datalayer-instances.ttl` |
| name (read-only) | `rdfs:label` | |
| type (read-only) | `martech:component_type` | `metric` or `dimension` |
| CJA description (read-only) | `rdfs:comment` | Shown for reference, distinct from the curated `definition` |
| CJA component ID, data view (read-only) | none | Derived from the `urn:cja:` ref, never stored separately |

## Local API (`server.py`)

`create_app(data_dir)` is a factory so the CLI can bind it to any data directory. Flask serves the bundled
`ui/` folder as static files and the JSON API under `/api/*` from the same origin, so there's no CORS.
Pages call the API with relative `fetch("/api/...")` URLs. It reuses `graph_explorer`, `journey_builder`,
`library` and `skill_builder` instead of duplicating their logic.

| Endpoint | Method | Used by |
|---|---|---|
| `/api/state` | GET | Most pages: mode, version, components, journeys, nav counts |
| `/api/mode` | POST | Mode switcher |
| `/api/settings` | GET, POST | XDM base URL on the Journeys page |
| `/api/components/<key>` | GET | Component edit page |
| `/api/components/<key>/context` | POST | Component edit page: save |
| `/api/cja/config` | GET, POST, DELETE | CJA connect dialog |
| `/api/cja/dataviews` | GET | CJA connect dialog |
| `/api/cja/sync` | POST | Components page: sync |
| `/api/journeys/generate` | POST | Journeys page: CSV import |
| `/api/journeys/save` | POST | Journey form |
| `/api/journeys/<slug>` | GET, DELETE | Journey form (load), Journeys page (delete) |
| `/api/library` | GET | Journeys page, journey form |
| `/api/library/<kind>` | POST | Create a requirement or KPI |
| `/api/library/<kind>/<id>` | POST | Edit a requirement or KPI |
| `/api/skills`, `/api/skills/<slug>` | GET, DELETE | Skills page |
| `/api/skills/generate` | POST | Skills page |
| `/api/data-files`, `/api/data-files/<name>` | GET | Data Files page |
| `/api/sources` | GET | Sources page, nav count |
| `/api/graph-data` | GET | Graph page |
| `/api/ttl-bundle` | GET | Query page |

**Component keys:** the UI's `component_key` (e.g. `product_views`) is the subject's local name without its
`component_` prefix (`component_product_views`). `find_component_file()` scans every instance file to find
which one defines a component.

## CJA sync

`cja_client.py` is a small standard-library client (`urllib`, no extra dependency).

- **Connect:** client ID, client secret, org ID and scopes are posted to `/api/cja/config`, which first
  requests a real token from Adobe IMS (`client_credentials` grant). Only if that works is the config
  saved to `.mkg-cja.json` (chmod 600 where supported). The secret is never returned by the API and never
  reaches the browser, a `.ttl` file or an `export-mcp` snapshot. Leaving the secret empty on reconfigure
  keeps the saved one. Tokens are cached in memory until shortly before they expire.
- **Sync:** pulls a data view's metrics and dimensions (paginated, tolerant of a bare list or a
  `{"content": [...]}` response) with `expansion=schemaPath`; without it CJA returns no path. Each new
  component gets:
  - `martech:refs` → `urn:cja:<dataViewId>:<componentId>`
  - `martech:refs` → `<xdm_base_url><schemaPath>`, only when CJA reports a real path. Derived fields
    report the literal `Derived Fields` and get no XDM ref.
  - CJA's description as `rdfs:comment`
- **Keys:** `component_key()` strips the `metrics/` or `variables/` prefix and lower-cases the rest. A
  metric and a dimension with the same key get a `_metric` / `_dimension` suffix.
- **Shared vs. custom components:** standard components (`SHARED_CJA_ID_PREFIXES` / `SHARED_CJA_IDS`:
  date and time-parting dimensions, `metrics/adobe_*`, Visits, Visitors, Occurrences) have the same ID in
  every data view, so they keep a single node; another data view only adds its `urn:cja:` ref. A custom
  component whose key already exists from another data view gets its own node, prefixed with that data
  view's slug (e.g. `dv_2_orders`), so each keeps its own context.
- **Re-sync is idempotent and only adds:** an existing component's curated fields are never touched. It
  only gains a missing XDM ref or description; an XDM ref built from an older base URL is replaced. The
  result warns while the XDM base URL is still the `SANDBOX_NAME` placeholder.
- CJA/IMS errors surface as readable messages (HTTP 502 from the local API) and never include the secret.
  CJA names are untrusted input: table cells are built with `textContent`.

`/api/sources` groups components by the data view in their `urn:cja:` refs. `last_synced` is the mtime of
`components-instances.ttl`, so it is per file, not per data view.

**Data view names** are shown as `Name (ID)` on the Sources page, the component edit page and the sync
dialog. A data view has no node in the graph, so its name isn't stored there. Instead, names are kept in
`.mkg-cja-dataviews.json`, refreshed every time `/api/cja/dataviews` lists the data views. If
`/api/sources` finds a data view without a known name and CJA is configured, it looks the names up once;
if CJA can't be reached, the page shows the ID alone.

## Components

- **Components page:** client-side search (name, CJA ID, XDM path, data layer variable, owner) and a filter
  for context status and metric/dimension, re-applied after every render. Columns have fixed widths with
  `.cell-truncate`, so long CJA IDs never push the Edit column off-screen. Context coverage always counts
  all rows. `component_summary()` in `server.py` supplies the per-row fields.
- **Data layer variables** are stored in `datalayer-instances.ttl`, separate from journey files, so
  regenerating a journey never overwrites a mapping.
  - A name that already exists as a `DataLayerVariable` anywhere is reused; only a new `maps_to` is written.
  - Mappings that come from a journey file are shown as read-only "from journey" and aren't sent back on save.
  - The save only touches mappings when the request body contains `data_layer_variables`.
  - Variables left without a mapping are dropped, and the file is deleted when its last mapping goes.

## Journeys

Three ways to author a journey, all through `journey_builder.py`:

- **Journey form** (`journey-edit.html`, reached from New journey / Edit): posts to `/api/journeys/save`.
  It validates required fields, slug format (`[a-z0-9][a-z0-9_-]*`, not reserved), a numeric target, at
  least one stage, and that every component exists. `new` refuses an existing slug (409). Stage order is
  row order; stage keys are slugified labels that stay stable when a stage is renamed.
- **CSV import** on the Journeys page (`/api/journeys/generate`), and `build_journey_from_csv()` /
  `build_journey_turtle()` from Python.

Design points:

- **Reuse, don't copy.** `existing_component_map()` finds components defined in other files; a journey
  references them by URI, so their curated context flows in. Only unknown keys are defined inline.
- **Editing is a reverse parse.** `journey_from_graph()` is the inverse of `build_journey_turtle()`. A
  file containing anything the builder can't write back (unknown classes or properties, several journeys,
  a stage without exactly one measurement) is refused with HTTP 409 and the reason, instead of being
  rewritten lossily. `_ROUND_TRIP_PREDICATES` is the allow-list.
- A journey's own legacy inline components and data layer variable are re-emitted verbatim, so editing
  never drops curated content.
- `entry_criteria` (per stage) is carried by the form, the CSV columns and the reverse parser.
- `_esc()` escapes backslashes and newlines, so multi-line text from the form produces valid Turtle.
- **XDM base URL:** `DEFAULT_XDM_BASE_URL = "https://sandbox/SANDBOX_NAME/xdm/"` is a placeholder.
  The org's value is stored in `.mkg-settings.json` (normalized to exactly one trailing `/`) and passed to
  the builder on every generation. It only affects journeys generated afterwards.
- **Journey diagram** on the form: a read-only row of stage cards built from the Stages table's DOM (no API
  call), re-rendered on every edit. It is deliberately flat, because journeys are an ordered list in the
  ontology with no branching, and there is no conversion data to show.
- **Delete** removes `<slug>-instances.ttl`, including any inline components it defined. Nothing outside a
  journey references its own nodes, so there are no dangling references to clean up.

## Shared requirement and KPI library

`library.py` reads and writes `library-instances.ttl` (org mode only). Entries are plain dicts so the API and
the form never handle RDF directly:

```
requirement: {id, label, comment}
kpi:         {id, label, formula, owner, target, comment}
```

An entry's ID is the local name of its URI (`req_<slug>` / `kpi_<slug>`) and never changes, so renaming an
entry doesn't break the journeys pointing at it. `GET /api/library` adds a usage count per entry. Deleting
a journey never deletes library entries. Journeys saved before the library existed keep their own
requirement and KPI until a library entry is picked for them.

## Graph and Query pages

These are the two pages that need JavaScript to function. Both load live data from the API and fall back
to embedded demo data when opened as a plain file. Vendored libraries live in `ui/vendor/` (no CDN).

- **Graph** (`graph.html`): `vis-network`, data from `/api/graph-data` (`extract_full_graph()`), fallback
  `EMBEDDED_DATA` in the page. Class filters, a journey selector that dims everything outside the selected
  journey, and a node detail panel.
- **Query** (`query.html`): [Oxigraph](https://github.com/oxigraph/oxigraph) compiled to WASM runs SPARQL
  1.1 in the browser over `/api/ttl-bundle`. To work from `file://`:
  - `oxigraph.web.js` is the package's `web.js` with `export` keywords stripped (a classic script instead
    of an ES module) and the async `__wbg_init` path removed (it needs `import.meta.url` and `fetch()`). It
    exposes `window.Oxigraph`.
  - `oxigraph.wasm.b64.js` holds the `web_bg.wasm` binary as a base64 string, passed to
    `Oxigraph.initSync()`.
  - `graph-data.ttl.js` holds the fallback Turtle as `ONTOLOGY_TTL`, `ECOMMERCE_TTL`, `LOGIN_TTL`.

**When the ontology or the bundled examples change, regenerate the fallbacks** (from the repo root, after
`npm install oxigraph vis-network` if you also need fresh vendor files; `node_modules/` is gitignored):

```
node -e "const fs=require('fs'); const d='src/martech_knowledge_graph/'; for (const [v,p] of Object.entries({ONTOLOGY_TTL:'ontology/martech-ontology.ttl',ECOMMERCE_TTL:'examples/ecommerce-funnel-instances.ttl',LOGIN_TTL:'examples/login-journey-instances.ttl'})) console.log('const '+v+' = '+JSON.stringify(fs.readFileSync(d+p,'utf-8'))+';');" > src/martech_knowledge_graph/ui/vendor/graph-data.ttl.js
python -c "import json; from martech_knowledge_graph import graph_explorer as ge; print(json.dumps(ge.extract_full_graph(ge.load_graph())))"
```

The second command's output replaces the `EMBEDDED_DATA` literal in `graph.html`. Upgrading Oxigraph means
repeating the `export` stripping and regenerating the base64 WASM file.

## MCP server

`mcp_server.py` runs as a separate process from `server.py`: Flask is WSGI and FastMCP's HTTP transport is
ASGI, so combining them would fight both frameworks. `mcp_server` is imported lazily in `cli.py`, so `serve`
doesn't pay for FastMCP's imports.

- **Tools:** `run_sparql(query)` and `get_ontology_schema()` (`extract_ontology_schema()`, read live from
  the ontology file so it can't drift). Both load a fresh graph per call from the active workspace.
- **Read-only by construction:** only `Graph.query()` is called, never `Graph.update()`. `.query()` parses
  the SPARQL Query grammar only, so `INSERT DATA` / `DELETE DATA` fail with a `ParseException` instead of
  executing.
- **Result shape:** MCP's `structuredContent` must be a JSON object, so every result is wrapped:
  `{"results": [...]}` for SELECT/CONSTRUCT/DESCRIBE, `{"result": true|false}` for ASK,
  `{"error": "..."}` on failure. ASK is detected via `SPARQLResult.type`, because rdflib's ASK result is
  bool-like but not a `bool`.
- **Transports:** `http` (default, `127.0.0.1:8931/mcp`, path set explicitly) and `stdio` (for Claude
  Desktop's local server config). In stdio mode all status output goes to stderr and the banner is
  disabled, because stdout is the protocol channel.
- **Hosted:** `export.py` (`export-mcp`) writes a folder with `server.py`, a snapshot of the
  `*-instances.ttl` files, a `requirements.txt` pinned to `@v<__version__>`, and deploy instructions for
  Prefect Horizon.

## Skills and the plugin marketplace

- **Skills page:** `skill_builder.build_skill_draft(g, name)` renders a skill from the live graph: the
  class list from `extract_ontology_schema()`, property descriptions from the ontology's own comments, and
  four example queries re-run at generation time to annotate their real row counts. The closing "Things to
  get right" section is a template for the org to fill in. Saved to `<data_dir>/skills/<slug>.md`; an
  existing name returns 409 unless `force` is set.
- **Plugin marketplace:** `build_plugin.py` regenerates `plugins/martech-kg/` from the ontology and
  instance files (bundled examples by default, or `--data-dir`). The plugin folder is generated output;
  don't edit it by hand, and don't commit a build from real org data to a public repo.

## UI shell

- Every page shares `css/style.css` and `js/mode-banner.js`. The script fetches `/api/state` once and
  renders:
  - the demo-mode banner;
  - the demo/org switcher and theme toggle in the sidebar footer (switching to org data asks for
    confirmation first);
  - the BETA badge and running version;
  - nav counts for Components, Journeys and Sources;
  - the mobile sidebar drawer (below 760px).

  If the API isn't reachable it does nothing.
- **Type colors:** each ontology class has a `--type-*` CSS variable, taken from the graph page's node
  colors, and a `.type-pill` component. Metric and dimension share the component color and are told apart
  by a filled or ring dot.
- **Home checklist:** steps 1 to 3 tick from real data (components synced, context added, journeys
  created). Steps 4 and 5 (view and query the graph) change no data, so they're tracked per browser via
  `localStorage["mkg-visited-<page>"]`.
- `localStorage` is only used for per-browser conveniences (theme, visited pages) and every access is
  wrapped in `try/catch`.
- **Writing style for user-facing text:** the product name is "MarTech Knowledge Graph: Context Layer
  Platform"; code identifiers (`martech-knowledge-graph`, the `martech:` prefix) are unchanged. UI copy
  avoids em dashes in sentences; "—" is only used as an empty-cell placeholder.
- Buttons have no default margin, so `.table-scroll` carries `margin-bottom` to keep a button below a table
  from sitting flush against it.

## Packaging and versioning

- `pip install -e .` installs the `martech-knowledge-graph` command (`cli.py`: `serve`, `mcp`,
  `export-mcp`). Requires Python 3.10+; very new Python releases may lack prebuilt wheels for some
  dependencies.
- `__version__` in `__init__.py` is the single source of truth: `pyproject.toml` reads it dynamically,
  `export-mcp` pins to it, and the UI shows the version of the running process (so a stale `serve`
  process shows the old number after an update).

## Known gaps

- A one-click "Start MCP" button on the MCP page (today: the CLI, or `export-mcp` for Horizon).
- Authentication on the MCP endpoint (it binds to `127.0.0.1` only by default).
- Validation rules (e.g. SHACL) that enforce the ontology regardless of how data was written.
- CJA calculated metrics and segments; components that disappear from CJA keep their stored context.
- Refreshing the component edit page's read-only CJA block live from CJA (it reads the local files).
- Merging existing duplicate requirements and KPIs into the library.
- No automated test suite yet.

## Troubleshooting

- **`ModuleNotFoundError: martech_knowledge_graph` when an MCP client spawns the stdio server:** look for
  a leftover `~artech_knowledge_graph-*.dist-info` folder in `site-packages` (left behind by an interrupted
  uninstall) and for a stale `martech-knowledge-graph.exe` process locking the console script. Stop the
  process, delete the folder, and run `pip install -e .` again.
