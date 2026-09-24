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
import re
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

import rdflib
from rdflib import RDF, RDFS, Namespace
from flask import Flask, jsonify, request, send_from_directory

from . import graph_explorer as ge
from . import journey_builder as jb
from . import __version__, cja_client
from .workspace import MODE_MARKER_NAME

PACKAGE_DIR = Path(__file__).resolve().parent
ONTOLOGY_FILE = PACKAGE_DIR / "ontology" / "martech-ontology.ttl"
EXAMPLES_DIR = PACKAGE_DIR / "examples"
UI_DIR = PACKAGE_DIR / "ui"
MARTECH = ge.MARTECH

def to_camel(key):
    parts = key.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def cja_component_id(key, ctype, refs):
    """The real CJA id if the component was synced (recorded as a urn:cja: ref), else a derived one."""
    for ref in refs:
        if ref.startswith(CJA_URN_PREFIX):
            return ref[len(CJA_URN_PREFIX):].split(":", 1)[-1]
    kind = "metrics" if ctype == "metric" else "dimensions"
    return f"{kind}/{to_camel(key)}"


def component_key_from_subject(subject):
    local = ge._local_name(subject)
    return local[len("component_"):] if local.startswith("component_") else local


SETTINGS_MARKER_NAME = ".mkg-settings.json"
CJA_CONFIG_NAME = ".mkg-cja.json"
CJA_URN_PREFIX = "urn:cja:"
DLV_FILE_NAME = "datalayer-instances.ttl"
DLV_NS = Namespace("https://example.org/martech/data/datalayer/")


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

    def dlv_file_path():
        return current_dir() / DLV_FILE_NAME

    def merged_instances():
        merged = rdflib.Graph()
        for fg in load_instance_file_graphs().values():
            merged += fg
        return merged

    def data_layer_variables_of(component):
        """[{name, source_system, editable}] for every DataLayerVariable mapped to this component.

        editable == the mapping lives in datalayer-instances.ttl (managed from the edit page); mappings that
        come from a generated journey file are shown read-only so regenerating a journey stays the only way
        to change those."""
        graphs = load_instance_file_graphs()
        merged = rdflib.Graph()
        for fg in graphs.values():
            merged += fg
        found = {}
        for path, fg in graphs.items():
            for d in fg.subjects(MARTECH.maps_to, component):
                entry = found.setdefault(d, {"editable": False})
                entry["editable"] = entry["editable"] or path.name == DLV_FILE_NAME
        rows = []
        for d, entry in found.items():
            source = merged.value(d, MARTECH.source_system)
            rows.append({
                "name": str(merged.value(d, RDFS.label) or ge._local_name(d)),
                "source_system": str(source) if source else "",
                "editable": entry["editable"],
            })
        return sorted(rows, key=lambda r: r["name"].lower())

    def save_data_layer_variables(component, rows):
        """Replace this component's mappings in datalayer-instances.ttl (never touches journey files)."""
        path = dlv_file_path()
        dg = rdflib.Graph()
        if path.exists():
            dg.parse(path, format="turtle")
        dg.bind("martech", ge.MARTECH)
        dg.bind("data", DLV_NS)
        dg.bind("rdfs", RDFS)

        known = {}
        merged = merged_instances()
        for d in merged.subjects(RDF.type, MARTECH.DataLayerVariable):
            known.setdefault(str(merged.value(d, RDFS.label) or ge._local_name(d)), d)

        for d in list(dg.subjects(MARTECH.maps_to, component)):
            dg.remove((d, MARTECH.maps_to, component))

        seen = set()
        for row in rows:
            name = ((row or {}).get("name") or "").strip()
            source = ((row or {}).get("source_system") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            subject = known.get(name)
            if subject is None:
                base = "dlv_" + (re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "variable")
                subject, n = DLV_NS[base], 2
                while (subject, RDF.type, MARTECH.DataLayerVariable) in merged:
                    subject, n = DLV_NS[f"{base}_{n}"], n + 1
                dg.add((subject, RDF.type, MARTECH.DataLayerVariable))
                dg.add((subject, RDFS.label, rdflib.Literal(name)))
                known[name] = subject
            if source and (subject, RDF.type, MARTECH.DataLayerVariable) in dg:
                for old in list(dg.objects(subject, MARTECH.source_system)):
                    dg.remove((subject, MARTECH.source_system, old))
                dg.add((subject, MARTECH.source_system, rdflib.Literal(source)))
            dg.add((subject, MARTECH.maps_to, component))

        for d in list(dg.subjects(RDF.type, MARTECH.DataLayerVariable)):
            if dg.value(d, MARTECH.maps_to) is None:
                for triple in list(dg.triples((d, None, None))):
                    dg.remove(triple)

        if len(dg) == 0:
            path.unlink(missing_ok=True)
            return
        header = (
            "# ==========================================================================\n"
            "# Data layer variable -> component mappings, maintained from the component edit page.\n"
            "# Kept separate from journey files so regenerating a journey never overwrites them.\n"
            "# ==========================================================================\n\n"
        )
        path.write_text(header + dg.serialize(format="turtle"), encoding="utf-8")

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
        refs = [str(o) for o in merged_graph.objects(subject, MARTECH.refs)]
        xdm_refs = sorted(r for r in refs if not r.startswith(CJA_URN_PREFIX))
        base = load_settings()["xdm_base_url"]
        xdm_path = ""
        if xdm_refs:
            xdm_path = xdm_refs[0][len(base):] if xdm_refs[0].startswith(base) else xdm_refs[0].rsplit("/", 1)[-1]
        dlv_names = sorted({str(merged_graph.value(d, RDFS.label) or ge._local_name(d))
                            for d in merged_graph.subjects(MARTECH.maps_to, subject)})
        return {
            "key": key,
            "name": label,
            "type": ctype,
            "data_layer_variables": dlv_names,
            "cja_id": cja_component_id(key, ctype, refs),
            "xdm_path": xdm_path,
            "xdm_ref": xdm_refs[0] if xdm_refs else "",
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
            "version": __version__,
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
            "cja_id": cja_component_id(key, ctype, refs),
            "definition": str(definition) if definition else "",
            "caveats": str(caveats) if caveats else "",
            "context": str(context) if context else "",
            "owner": str(owner) if owner else "",
            "refs": refs,
            "cja_description": str(g.value(s, RDFS.comment) or ""),
            "data_layer_variables": data_layer_variables_of(s),
            "dlv_suggestions": sorted({str(m.value(d, RDFS.label) or ge._local_name(d))
                                       for m in [merged_instances()]
                                       for d in m.subjects(RDF.type, MARTECH.DataLayerVariable)}),
            "data_view_id": next((r[len(CJA_URN_PREFIX):].split(":", 1)[0] for r in refs if r.startswith(CJA_URN_PREFIX)), ""),
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

        if isinstance(body.get("data_layer_variables"), list):
            save_data_layer_variables(s, body["data_layer_variables"])

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

    cja_config_path = data_dir / CJA_CONFIG_NAME
    cja_clients = {}

    def load_cja_config():
        try:
            return json.loads(cja_config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def get_cja_client():
        cfg = load_cja_config()
        if not cfg:
            return None
        cache_key = (cfg["client_id"], cfg["client_secret"], cfg["org_id"], cfg["scopes"])
        if cache_key not in cja_clients:
            cja_clients.clear()
            cja_clients[cache_key] = cja_client.CjaClient(*cache_key)
        return cja_clients[cache_key]

    @app.route("/api/cja/config", methods=["GET"])
    def api_get_cja_config():
        cfg = load_cja_config()
        if not cfg:
            return jsonify({"configured": False, "scopes": cja_client.DEFAULT_SCOPES})
        return jsonify({
            "configured": True, "client_id": cfg["client_id"], "org_id": cfg["org_id"], "scopes": cfg["scopes"],
        })

    @app.route("/api/cja/config", methods=["POST"])
    def api_save_cja_config():
        blocked = require_org_mode()
        if blocked:
            return blocked

        body = request.get_json(force=True)
        existing = load_cja_config() or {}
        cfg = {
            "client_id": (body.get("client_id") or "").strip(),
            "client_secret": (body.get("client_secret") or "").strip() or existing.get("client_secret", ""),
            "org_id": (body.get("org_id") or "").strip(),
            "scopes": (body.get("scopes") or "").strip() or cja_client.DEFAULT_SCOPES,
        }
        if not (cfg["client_id"] and cfg["client_secret"] and cfg["org_id"]):
            return jsonify({"error": "Client ID, client secret and organization ID are required."}), 400

        try:
            cja_client.CjaClient(**cfg).token()
        except cja_client.CjaError as exc:
            return jsonify({"error": f"Could not get a token: {exc}"}), 400

        data_dir.mkdir(parents=True, exist_ok=True)
        cja_config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        try:
            cja_config_path.chmod(0o600)
        except OSError:
            pass
        return jsonify({"ok": True, "org_id": cfg["org_id"]})

    @app.route("/api/cja/config", methods=["DELETE"])
    def api_delete_cja_config():
        blocked = require_org_mode()
        if blocked:
            return blocked
        cja_config_path.unlink(missing_ok=True)
        cja_clients.clear()
        return jsonify({"ok": True})

    @app.route("/api/cja/dataviews", methods=["GET"])
    def api_cja_dataviews():
        blocked = require_org_mode()
        if blocked:
            return blocked
        client = get_cja_client()
        if client is None:
            return jsonify({"error": "CJA is not configured yet."}), 400
        try:
            return jsonify({"data_views": client.list_data_views()})
        except cja_client.CjaError as exc:
            return jsonify({"error": str(exc)}), 502

    @app.route("/api/cja/sync", methods=["POST"])
    def api_cja_sync():
        blocked = require_org_mode()
        if blocked:
            return blocked

        dv_id = (request.get_json(force=True) or {}).get("data_view_id")
        client = get_cja_client()
        if client is None:
            return jsonify({"error": "CJA is not configured yet."}), 400
        if not dv_id:
            return jsonify({"error": "data_view_id is required"}), 400

        try:
            pulled = client.list_components(dv_id)
        except cja_client.CjaError as exc:
            return jsonify({"error": str(exc)}), 502

        known_types, known_refs = {}, set()
        for fg in load_instance_file_graphs().values():
            for subj in fg.subjects(RDF.type, MARTECH.Component):
                known_types[component_key_from_subject(subj)] = str(fg.value(subj, MARTECH.component_type) or "")
                known_refs.update(str(o) for o in fg.objects(subj, MARTECH.refs))

        sync_file = cja_sync_file()
        cja_ns = Namespace("https://example.org/martech/data/cja_sync/")
        g = rdflib.Graph()
        if sync_file.exists():
            g.parse(sync_file, format="turtle")
        g.bind("martech", ge.MARTECH)
        g.bind("data", cja_ns)
        g.bind("rdfs", RDFS)

        xdm_base_url = load_settings()["xdm_base_url"]
        subject_by_ref = {str(o): s for s in g.subjects(RDF.type, MARTECH.Component) for o in g.objects(s, MARTECH.refs)}

        added = {"metric": 0, "dimension": 0}
        skipped = 0
        enriched = 0
        for comp in pulled:
            ref = f"{CJA_URN_PREFIX}{dv_id}:{comp['id']}"
            xdm_ref = rdflib.URIRef(xdm_base_url + comp["schema_path"]) if comp["schema_path"] else None
            key = cja_client.component_key(comp["id"])
            if key in known_types and known_types[key] != comp["type"]:
                key += "_" + comp["type"]
            if ref in subject_by_ref:
                # Already synced: only ever ADD what is missing, never touch curated fields.
                subject = subject_by_ref[ref]
                changed = False
                if xdm_ref is not None and (subject, MARTECH.refs, xdm_ref) not in g:
                    # An XDM ref built from an older base URL (same path, different prefix) is replaced.
                    for old in list(g.objects(subject, MARTECH.refs)):
                        if str(old).startswith("http") and str(old).rsplit("/", 1)[-1] == comp["schema_path"]:
                            g.remove((subject, MARTECH.refs, old))
                    g.add((subject, MARTECH.refs, xdm_ref))
                    changed = True
                if comp["description"] and g.value(subject, RDFS.comment) is None:
                    g.add((subject, RDFS.comment, rdflib.Literal(comp["description"])))
                    changed = True
                enriched += changed
                skipped += 1
                continue
            if ref in known_refs or key in known_types:
                skipped += 1
                continue
            known_types[key] = comp["type"]
            known_refs.add(ref)
            subject = cja_ns["component_" + key]
            g.add((subject, RDF.type, MARTECH.Component))
            g.add((subject, RDFS.label, rdflib.Literal(comp["name"])))
            g.add((subject, MARTECH.component_type, rdflib.Literal(comp["type"])))
            g.add((subject, MARTECH.refs, rdflib.URIRef(ref)))
            if xdm_ref is not None:
                g.add((subject, MARTECH.refs, xdm_ref))
            if comp["description"]:
                g.add((subject, RDFS.comment, rdflib.Literal(comp["description"])))
            added[comp["type"]] += 1

        if sum(added.values()) or enriched:
            header = (
                "# ==========================================================================\n"
                "# Components synced from CJA, not yet bound to any journey.\n"
                "# Written by the local API's /api/cja/sync -- context still needs curating\n"
                "# via component-edit.html before this component is useful in the graph.\n"
                "# ==========================================================================\n\n"
            )
            sync_file.write_text(header + g.serialize(format="turtle"), encoding="utf-8")

        return jsonify({
            "added": added, "skipped": skipped, "enriched": enriched, "total_pulled": len(pulled),
            "xdm_base_url": xdm_base_url, "xdm_base_url_is_default": xdm_base_url == jb.DEFAULT_XDM_BASE_URL,
            "state": collect_state(),
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
            own_file = current_dir() / f"{slug}-instances.ttl"
            existing = {}
            for path, fg in load_instance_file_graphs().items():
                if path == own_file:
                    continue
                for subj in fg.subjects(RDF.type, MARTECH.Component):
                    existing.setdefault(component_key_from_subject(subj), str(subj))
            turtle_text = jb.build_journey_from_csv(
                tmp_path, xdm_base_url=load_settings()["xdm_base_url"], existing_components=existing
            )
            used = {r["component_key"].strip() for r in rows}
            reused = sorted(used & existing.keys())
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

        out_path = current_dir() / f"{slug}-instances.ttl"
        out_path.write_text(turtle_text, encoding="utf-8")

        return jsonify({"ok": True, "slug": slug, "file": out_path.name, "turtle": turtle_text,
                        "reused_components": reused})

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
