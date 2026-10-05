"""Build the Coworker plugin in plugins/martech-kg from the knowledge graph source files.

Run after any change to the ontology or the instance files. Everything under
plugins/martech-kg/skills/martech-kg/references/ is regenerated, so do not edit it by hand.
"""

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

from rdflib import RDFS

from martech_knowledge_graph import graph_explorer as ge

REPO_ROOT = Path(__file__).resolve().parent
REFERENCES_DIR = REPO_ROOT / "plugins" / "martech-kg" / "skills" / "martech-kg" / "references"
PREFIX = f"PREFIX martech: <{ge.MARTECH}>\nPREFIX rdfs: <{RDFS}>\n"


def run(g, body, **bindings):
    return list(g.query(PREFIX + body, initBindings=bindings))


def text(term, fallback="not set"):
    return str(term) if term is not None and str(term) != "" else fallback


def inline(term, fallback="not set"):
    """Value for use mid-sentence: drops a trailing period so the sentence's own period doesn't double up."""
    return text(term, fallback).rstrip(".")


def xdm_path(refs_uri):
    marker = "/xdm/"
    return refs_uri.split(marker, 1)[1] if marker in refs_uri else ""


def stage_order(row):
    try:
        return int(str(row.order))
    except (TypeError, ValueError):
        return 0


def journey_section(g, journey):
    lines = []
    owner = run(g, "SELECT ?owner WHERE { ?j martech:owner ?owner }", j=journey.journey)
    lines += [f"## {text(journey.label)}", ""]
    lines.append(f"- Journey owner: {text(owner[0].owner) if owner else 'not set'}")

    kpi_uris = sorted({r.kpi for r in run(g, "SELECT DISTINCT ?kpi WHERE { ?j martech:has_stage ?s . ?s martech:rolls_up_to ?kpi }", j=journey.journey)}, key=str)
    for kpi in kpi_uris:
        k = run(g, "SELECT ?label ?formula ?target ?owner ?comment WHERE { ?k rdfs:label ?label . OPTIONAL { ?k martech:formula ?formula } OPTIONAL { ?k martech:target ?target } OPTIONAL { ?k martech:owner ?owner } OPTIONAL { ?k rdfs:comment ?comment } }", k=kpi)[0]
        reqs = sorted(run(g, "SELECT ?req ?label ?comment ?status WHERE { ?req martech:addressed_by ?k ; rdfs:label ?label . OPTIONAL { ?req rdfs:comment ?comment } OPTIONAL { ?req martech:status ?status } }", k=kpi), key=lambda r: str(r.label))
        for req in reqs:
            lines.append(f"- Requirement: {inline(req.label)}. Comment: {inline(req.comment)}. Status: {inline(req.status)}.")
        lines.append(f"- KPI: {inline(k.label)}. Formula: {inline(k.formula)}. Target: {inline(k.target)}. Owner: {inline(k.owner)}. Comment: {inline(k.comment)}.")
    lines.append("")

    lines += ["### Stages", ""]
    stages = run(g, "SELECT ?stage ?label ?order WHERE { ?j martech:has_stage ?stage . ?stage rdfs:label ?label . OPTIONAL { ?stage martech:order ?order } }", j=journey.journey)
    for st in sorted(stages, key=lambda r: (stage_order(r), str(r.label))):
        meas = run(g, "SELECT ?compLabel ?ctype ?filter WHERE { ?m martech:measured_entity ?s ; martech:measured_component ?c . ?c rdfs:label ?compLabel . OPTIONAL { ?c martech:component_type ?ctype } OPTIONAL { ?m martech:filter_value ?filter } }", s=st.stage)
        rolls = bool(run(g, "SELECT ?k WHERE { ?s martech:rolls_up_to ?k }", s=st.stage))
        if meas:
            m = sorted(meas, key=lambda r: str(r.compLabel))[0]
            measured = f"{inline(m.compLabel)} ({inline(m.ctype)})"
            filt = inline(m.filter, "none")
        else:
            measured, filt = "not set", "none"
        lines.append(f"{stage_order(st)}. {inline(st.label)}. Measured by: {measured}. Filter value: {filt}. Rolls up to KPI: {'yes' if rolls else 'no'}.")
    lines.append("")

    lines += ["### Components used by this journey", ""]
    comp_uris = {r.comp for r in run(g, "SELECT DISTINCT ?comp WHERE { ?j martech:has_stage ?s . ?m martech:measured_entity ?s ; martech:measured_component ?comp }", j=journey.journey)}
    comp_rows = []
    for c in comp_uris:
        d = run(g, "SELECT ?label ?ctype ?definition ?caveats ?context ?owner WHERE { ?c rdfs:label ?label . OPTIONAL { ?c martech:component_type ?ctype } OPTIONAL { ?c martech:definition ?definition } OPTIONAL { ?c martech:caveats ?caveats } OPTIONAL { ?c martech:context ?context } OPTIONAL { ?c martech:owner ?owner } }", c=c)[0]
        refs = sorted(str(r.refs) for r in run(g, "SELECT ?refs WHERE { ?c martech:refs ?refs }", c=c))
        dlvs = sorted(str(r.label) for r in run(g, "SELECT ?label WHERE { ?v martech:maps_to ?c ; rdfs:label ?label }", c=c))
        comp_rows.append((text(d.label), str(c), d, refs, dlvs))
    for label, _uri, d, refs, dlvs in sorted(comp_rows, key=lambda row: (row[0], row[1])):
        xdm = ", ".join(xdm_path(r) for r in refs if xdm_path(r)) or "not set"
        lines.append(f"- {label} ({text(d.ctype)})")
        lines.append(f"  - XDM path: {xdm}")
        lines.append(f"  - Refs URI: {', '.join(refs) if refs else 'not set'}")
        lines.append(f"  - Definition: {text(d.definition)}")
        lines.append(f"  - Caveats: {text(d.caveats)}")
        lines.append(f"  - Context: {text(d.context)}")
        lines.append(f"  - Owner: {text(d.owner)}")
        lines.append(f"  - Data layer variables: {', '.join(dlvs) if dlvs else 'none mapped'}")
    lines.append("")
    return lines


def build_snapshot(g, sources):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    header = [
        "# Martech knowledge graph snapshot",
        "",
        f"- Generated: {now}",
        f"- Source files: {', '.join(sources)}",
        f"- Triple count: {len(g)}",
        "",
        "How to read this file:",
        "1. Each section is one journey: requirement and KPI first, then its stages in order, then the components they use.",
        "2. Caveats and owners are curated business context; quote them together with the component they describe.",
        "3. Anything missing here may still be in the references/ files, so check there before saying it is not in the graph.",
        "",
    ]
    journeys = sorted(run(g, "SELECT ?journey ?label WHERE { ?journey a martech:Journey ; rdfs:label ?label }"), key=lambda r: (str(r.label), str(r.journey)))
    body = []
    for j in journeys:
        body += journey_section(g, j)
    return "\n".join(header + body).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=ge.EXAMPLES_DIR,
                        help="Folder with *-instances.ttl files. Default: the bundled generic demo data.")
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()

    instance_files = sorted(data_dir.glob("*-instances.ttl"))
    if not instance_files:
        raise SystemExit(f"No *-instances.ttl files found in {data_dir}")
    if data_dir != ge.EXAMPLES_DIR.resolve():
        print("WARNING: building from a non-bundled data folder. The output will contain that data;")
        print("         do not commit references/ to a public repository.")

    if REFERENCES_DIR.exists():
        shutil.rmtree(REFERENCES_DIR)
    REFERENCES_DIR.mkdir(parents=True)
    shutil.copy2(ge.ONTOLOGY_FILE, REFERENCES_DIR / ge.ONTOLOGY_FILE.name)
    for f in instance_files:
        shutil.copy2(f, REFERENCES_DIR / f.name)

    g = ge.load_graph(ontology_path=ge.ONTOLOGY_FILE, script_dir=data_dir)
    sources = [ge.ONTOLOGY_FILE.name] + [f.name for f in instance_files]
    snapshot_path = REFERENCES_DIR / "context-snapshot.md"
    snapshot_path.write_text(build_snapshot(g, sources), encoding="utf-8", newline="\n")

    print(f"Copied {len(sources)} file(s) into {REFERENCES_DIR.relative_to(REPO_ROOT)}:")
    for name in sources:
        print(f"  - {name}")
    print(f"Triple count: {len(g)}")
    print(f"Snapshot: {snapshot_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
