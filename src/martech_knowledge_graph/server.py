"""
Local API + UI server.

Serves the bundled ui/ folder as static files, plus a small JSON API under
/api/*. This is what turns the ui/ pages from several self-contained
simulations into one real pipeline: components.html/component-edit.html/
journeys.html write to the actual *-instances.ttl files in the configured
data directory, and graph.html/query.html read the current state of those
same files instead of a snapshot baked in at authoring time.

Every ui/*.html page still works standalone (its own copy, opened directly
via file://, no server) -- it just falls back to its static/embedded
content if this server isn't reachable. Nothing here replaces the flat
.ttl files as the storage layer; it only reads and writes them, reusing
graph_explorer.py's and journey_builder.py's existing functions rather
than duplicating them.

Two real workspaces, not a copy-files toggle: "demo" mode reads/writes the
package's bundled, read-only examples/ directory; "org" mode reads/writes
the caller-provided data_dir. POST /api/mode switches between them at
runtime (persisted in a .mkg-mode marker file in data_dir); write endpoints
refuse to run while in demo mode. See ui/js/mode-banner.js for the shared
banner + switcher every page includes.

Run via the CLI:
    martech-knowledge-graph serve
"""

import csv
import io
import json
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

import rdflib
from rdflib import RDF, RDFS, Namespace
from flask import Flask, jsonify, request, send_from_directory

from . import graph_explorer as ge
from . import journey_builder as jb

PACKAGE_DIR = Path(__file__).resolve().parent
ONTOLOGY_FILE = PACKAGE_DIR / "ontology" / "martech-ontology.ttl"
EXAMPLES_DIR = PACKAGE_DIR / "examples"
UI_DIR = PACKAGE_DIR / "ui"
MARTECH = ge.MARTECH

# Stand-in for what a real CJA Semantic Layer MCP pull would return for each
# data view -- mirrors the mock pull table that used to live only in
# components.html's inline script.
CJA_DATA_VIEWS = {
    "dv_prod_web": "Production - Website",
    "dv_prod_app": "Production - Mobile App",
    "dv_staging_web": "Staging - Website",
}
CJA_MOCK_PULL = {
    "dv_prod_web": {"key": "cart_removes", "name": "Cart removes", "type": "metric"},
    "dv_prod_app": {"key": "app_session_starts", "name": "App session starts", "type": "metric"},
    "dv_staging_web": {"key": "page_name_staging", "name": "Page name (staging)", "type": "dimension"},
}


def to_camel(key):
    parts = key.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def mock_cja_component_id(key, ctype):
    kind = "metrics" if ctype == "metric" else "dimensions"
    return f"cja:{kind}/{to_camel(key)}"


def component_key_from_subject(subject):
    local = ge._local_name(subject)
    return local[len("component_"):] if local.startswith("component_") else local


MODE_MARKER_NAME = ".mkg-mode"
SETTINGS_MARKER_NAME = ".mkg-settings.json"


def create_app(data_dir: Path) -> Flask:
    """Build the Flask app.

    Two real workspaces, not a copy-files toggle: "demo" reads/writes the
    bundled, read-only EXAMPLES_DIR; "org" reads/writes the caller-provided
    data_dir. current_dir() resolves which one is active on every request, so
    switching modes (POST /api/mode) takes effect immediately for every
    endpoint below -- nothing needs restarting.
    """
    data_dir = Path(data_dir)
    mode_marker = data_dir / MODE_MARKER_NAME
    settings_marker = data_dir / SETTINGS_MARKER_NAME
    state = {"mode": mode_marker.read_text(encoding="utf-8").strip() if mode_marker.exists() else "demo"}
    if state["mode"] not in ("demo", "org"):
        state["mode"] = "demo"

    app = Flask(__name__, static_folder=str(UI_DIR), static_url_path="")

    def current_dir():
        return EXAMPLES_DIR if state["mode"] == "demo" else data_dir

    def cja_sync_file():
        return current_dir() / "components-instances.ttl"

    def require_org_mode():
        """Returns a (jsonify(...), 403) tuple if in demo mode, else None."""
        if state["mode"] == "demo":
            return jsonify({
                "error": "Demo data is read-only — switch to your own data (top right) to make edits.",
            }), 403
        return None

    def load_settings():
        """Org-workspace settings (e.g. the XDM base URL used for generated refs).

        Always reads from data_dir regardless of active mode -- same as the
        .mkg-mode marker, this is metadata about the org workspace itself,
        never written to the read-only bundled EXAMPLES_DIR.
        """
        settings = {"xdm_base_url": jb.DEFAULT_XDM_BASE_URL}
        if settings_marker.exists():
            try:
                settings.update(json.loads(settings_marker.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass
        return settings

    def save_settings(new_settings):
        settings_marker.write_text(json.dumps(new_settings, indent=2), encoding="utf-8")

    def load_instance_file_graphs():
        """{Path: rdflib.Graph} for every *-instances.ttl in the active directory."""
        graphs = {}
        for path in sorted(current_dir().glob("*-instances.ttl")):
            g = rdflib.Graph()
            g.parse(path, format="turtle")
            graphs[path] = g
        return graphs

    def find_component_file(key):
        """Returns (path, file_graph, subject) for the component with this key, or (None, None, None)."""
        target = "component_" + key
        for path, g in load_instance_file_graphs().items():
            for s in g.subjects(RDF.type, MARTECH.Component):
                if ge._local_name(s) == target:
                    return path, g, s
        return None, None, None

    def component_summary(merged_graph, subject):
        key = component_key_from_subject(subject)
        label = str(merged_graph.value(subject, RDFS.label) or key)
        ctype = str(merged_graph.value(subject, MARTECH.component_type) or "")
        owner = merged_graph.value(subject, MARTECH.owner)
        definition = merged_graph.value(subject, MARTECH.definition)
        caveats = merged_graph.value(subject, MARTECH.caveats)
        context = merged_graph.value(subject, MARTECH.context)
        has_context = bool(definition and caveats and context and owner)
        return {
            "key": key,
            "name": label,
            "type": ctype,
            "cja_id": mock_cja_component_id(key, ctype),
            "owner": str(owner) if owner else "",
            "has_context": has_context,
        }

    def collect_state():
        merged = rdflib.Graph()
        merged.parse(ONTOLOGY_FILE, format="turtle")
        file_graphs = load_instance_file_graphs()
        for g in file_graphs.values():
            merged += g

        components = [component_summary(merged, s) for s in merged.subjects(RDF.type, MARTECH.Component)]
        components.sort(key=lambda c: c["name"])

        journeys = []
        for path, g in file_graphs.items():
            for s in g.subjects(RDF.type, MARTECH.Journey):
                label = str(g.value(s, RDFS.label) or ge._local_name(s))
                stages = len(list(g.objects(s, MARTECH.has_stage)))
                kpis = len(list(g.subjects(RDF.type, MARTECH.KPI)))
                requirements = list(g.subjects(RDF.type, MARTECH.Requirement))
                requirement = str(g.value(requirements[0], RDFS.label)) if requirements else ""
                mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
                journeys.append({
                    "slug": path.name.replace("-instances.ttl", ""),
                    "label": label,
                    "requirement": requirement,
                    "stages": stages,
                    "kpis": kpis,
                    "last_generated": mtime,
                })
        journeys.sort(key=lambda j: j["label"])

        return {
            "mode": state["mode"],
            "components": components,
            "journeys": journeys,
            "triple_count": len(merged),
        }

    @app.route("/")
    def index():
        return send_from_directory(UI_DIR, "index.html")

    @app.route("/api/state", methods=["GET"])
    def api_state():
        return jsonify(collect_state())

    @app.route("/api/mode", methods=["POST"])
    def api_set_mode():
        body = request.get_json(force=True)
        new_mode = body.get("mode")
        if new_mode not in ("demo", "org"):
            return jsonify({"error": "mode must be 'demo' or 'org'"}), 400
        state["mode"] = new_mode
        mode_marker.write_text(new_mode, encoding="utf-8")
        return jsonify({"mode": state["mode"], "state": collect_state()})

    @app.route("/api/settings", methods=["GET"])
    def api_get_settings():
        return jsonify(load_settings())

    @app.route("/api/settings", methods=["POST"])
    def api_save_settings():
        blocked = require_org_mode()
        if blocked:
            return blocked

        body = request.get_json(force=True)
        xdm_base_url = (body.get("xdm_base_url") or "").strip()
        if not xdm_base_url:
            return jsonify({"error": "xdm_base_url must not be empty"}), 400
        xdm_base_url = xdm_base_url.rstrip("/") + "/"

        settings = load_settings()
        settings["xdm_base_url"] = xdm_base_url
        save_settings(settings)
        return jsonify(settings)

    @app.route("/api/components/<key>", methods=["GET"])
    def api_get_component(key):
        path, g, s = find_component_file(key)
        if s is None:
            return jsonify({"error": f"no component with key '{key}'"}), 404

        definition = g.value(s, MARTECH.definition)
        caveats = g.value(s, MARTECH.caveats)
        context = g.value(s, MARTECH.context)
        owner = g.value(s, MARTECH.owner)
        refs = [str(o) for o in g.objects(s, MARTECH.refs)]
        ctype = str(g.value(s, MARTECH.component_type) or "")

        return jsonify({
            "key": key,
            "name": str(g.value(s, RDFS.label) or key),
            "type": ctype,
            "cja_id": mock_cja_component_id(key, ctype),
            "definition": str(definition) if definition else "",
            "caveats": str(caveats) if caveats else "",
            "context": str(context) if context else "",
            "owner": str(owner) if owner else "",
            "refs": refs,
            "source_file": path.name,
        })

    @app.route("/api/components/<key>/context", methods=["POST"])
    def api_save_component_context(key):
        blocked = require_org_mode()
        if blocked:
            return blocked

        path, g, s = find_component_file(key)
        if s is None:
            return jsonify({"error": f"no component with key '{key}'"}), 404

        body = request.get_json(force=True)

        for pred in (MARTECH.definition, MARTECH.caveats, MARTECH.context, MARTECH.owner, MARTECH.refs):
            for o in list(g.objects(s, pred)):
                g.remove((s, pred, o))

        g.add((s, MARTECH.definition, rdflib.Literal(body.get("definition", ""))))
        g.add((s, MARTECH.caveats, rdflib.Literal(body.get("caveats", ""))))
        g.add((s, MARTECH.context, rdflib.Literal(body.get("context", ""))))
        g.add((s, MARTECH.owner, rdflib.Literal(body.get("owner", ""))))
        for ref in body.get("refs", []):
            url = (ref or {}).get("url", "").strip()
            if url:
                g.add((s, MARTECH.refs, rdflib.URIRef(url)))

        path.write_text(g.serialize(format="turtle"), encoding="utf-8")

        preview = rdflib.Graph()
        preview.bind("martech", ge.MARTECH)
        preview.bind("rdfs", RDFS)
        for prefix, ns in g.namespaces():
            if prefix == "data":
                preview.bind("data", ns)
        for p, o in g.predicate_objects(s):
            preview.add((s, p, o))
        turtle_snippet = preview.serialize(format="turtle")

        return jsonify({"ok": True, "turtle": turtle_snippet})

    @app.route("/api/cja/sync", methods=["POST"])
    def api_cja_sync():
        blocked = require_org_mode()
        if blocked:
            return blocked

        body = request.get_json(force=True)
        dv_id = body.get("data_view_id")
        if dv_id not in CJA_DATA_VIEWS:
            return jsonify({"error": f"unknown data_view_id '{dv_id}'"}), 400

        pull = CJA_MOCK_PULL[dv_id]
        _, _, existing = find_component_file(pull["key"])
        if existing is not None:
            return jsonify({"added": False, "data_view": CJA_DATA_VIEWS[dv_id], "state": collect_state()})

        sync_file = cja_sync_file()
        cja_ns = Namespace("https://example.org/martech/data/cja_sync/")
        if sync_file.exists():
            g = rdflib.Graph()
            g.parse(sync_file, format="turtle")
        else:
            g = rdflib.Graph()
        g.bind("martech", ge.MARTECH)
        g.bind("data", cja_ns)
        g.bind("rdfs", RDFS)

        subject = cja_ns["component_" + pull["key"]]
        g.add((subject, RDF.type, MARTECH.Component))
        g.add((subject, RDFS.label, rdflib.Literal(pull["name"])))
        g.add((subject, MARTECH.component_type, rdflib.Literal(pull["type"])))

        header = (
            "# ==========================================================================\n"
            "# Components synced from CJA, not yet bound to any journey.\n"
            "# Written by the local API's /api/cja/sync -- context still needs curating\n"
            "# via component-edit.html before this component is useful in the graph.\n"
            "# ==========================================================================\n\n"
        )
        sync_file.write_text(header + g.serialize(format="turtle"), encoding="utf-8")

        return jsonify({
            "added": True, "data_view": CJA_DATA_VIEWS[dv_id], "component": pull, "state": collect_state(),
        })

    @app.route("/api/journeys/generate", methods=["POST"])
    def api_generate_journey():
        blocked = require_org_mode()
        if blocked:
            return blocked

        body = request.get_json(force=True)
        csv_text = body.get("csv_text", "")
        tmp_path = None

        try:
            rows = list(csv.DictReader(io.StringIO(csv_text)))
            if not rows:
                raise ValueError("CSV has no data rows")
            slug = rows[0]["journey_slug"].strip()
            if not slug:
                raise ValueError("journey_slug is required in the first row")

            with NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8") as tmp:
                tmp.write(csv_text)
                tmp_path = tmp.name
            turtle_text = jb.build_journey_from_csv(tmp_path, xdm_base_url=load_settings()["xdm_base_url"])
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

        out_path = current_dir() / f"{slug}-instances.ttl"
        out_path.write_text(turtle_text, encoding="utf-8")

        return jsonify({"ok": True, "slug": slug, "file": out_path.name, "turtle": turtle_text})

    @app.route("/api/graph-data", methods=["GET"])
    def api_graph_data():
        g = ge.load_graph(ontology_path=ONTOLOGY_FILE, script_dir=current_dir())
        return jsonify(ge.extract_full_graph(g))

    @app.route("/api/ttl-bundle", methods=["GET"])
    def api_ttl_bundle():
        instances = {}
        for path in sorted(current_dir().glob("*-instances.ttl")):
            instances[path.name] = path.read_text(encoding="utf-8")
        return jsonify({
            "ontology": ONTOLOGY_FILE.read_text(encoding="utf-8"),
            "instances": instances,
        })

    return app
