"""
Shared requirement and KPI library.

A requirement or KPI that several journeys use is defined once, in library-instances.ttl in the org data
directory, and each journey file refers to it by URI, the same way journeys share components. The library
exists only in org mode: the bundled demo data has no library file and the library endpoints refuse writes
there.

Entries are plain dicts so the form and the API never handle RDF directly:
    requirement: {id, label, comment}
    kpi:         {id, label, formula, owner, target, comment}
An entry's id is the local name of its URI (req_<slug> or kpi_<slug>); it never changes after creation, so
renaming an entry does not break the journeys that point at it.
"""

import rdflib
from rdflib import RDF, RDFS, Literal, Namespace

from . import graph_explorer as ge
from .journey_builder import LIBRARY_NS, slugify

LIBRARY_FILE_NAME = "library-instances.ttl"
LIB = Namespace(LIBRARY_NS)
MARTECH = ge.MARTECH

HEADER = (
    "# ==========================================================================\n"
    "# Shared requirements and KPIs. Maintained from the journeys page.\n"
    "# Journey files refer to these entries by URI; edit them here, not in a journey file.\n"
    "# ==========================================================================\n\n"
)


def _text(g, subject, pred):
    value = g.value(subject, pred)
    return str(value) if value is not None else ""


def read_entries(path):
    """{'requirements': [...], 'kpis': [...]} from the library file; empty lists when there is no file."""
    g = rdflib.Graph()
    if path.exists():
        g.parse(path, format="turtle")
    requirements = [
        {"id": ge._local_name(s), "label": _text(g, s, RDFS.label), "comment": _text(g, s, RDFS.comment)}
        for s in sorted(g.subjects(RDF.type, MARTECH.Requirement), key=str)
    ]
    kpis = []
    for s in sorted(g.subjects(RDF.type, MARTECH.KPI), key=str):
        target = g.value(s, MARTECH.target)
        kpis.append({
            "id": ge._local_name(s), "label": _text(g, s, RDFS.label), "formula": _text(g, s, MARTECH.formula),
            "owner": _text(g, s, MARTECH.owner), "target": float(target) if target is not None else None,
            "comment": _text(g, s, RDFS.comment),
        })
    return {"requirements": requirements, "kpis": kpis}


def write_entries(path, entries):
    """Rewrite the whole library file from entry dicts. Removes the file when the library is empty."""
    g = rdflib.Graph()
    g.bind("martech", MARTECH)
    g.bind("rdfs", RDFS)
    g.bind("lib", LIB)
    for r in entries["requirements"]:
        s = LIB[r["id"]]
        g.add((s, RDF.type, MARTECH.Requirement))
        g.add((s, RDFS.label, Literal(r["label"])))
        if r.get("comment"):
            g.add((s, RDFS.comment, Literal(r["comment"])))
        g.add((s, MARTECH.status, Literal("active")))
    for k in entries["kpis"]:
        s = LIB[k["id"]]
        g.add((s, RDF.type, MARTECH.KPI))
        g.add((s, RDFS.label, Literal(k["label"])))
        g.add((s, MARTECH.formula, Literal(k["formula"])))
        g.add((s, MARTECH.owner, Literal(k["owner"])))
        if k.get("target") is not None:
            g.add((s, MARTECH.target, Literal(float(k["target"]))))
        if k.get("comment"):
            g.add((s, RDFS.comment, Literal(k["comment"])))
    if len(g) == 0:
        path.unlink(missing_ok=True)
        return
    path.write_text(HEADER + g.serialize(format="turtle"), encoding="utf-8")


def new_id(prefix, label, taken):
    """A fresh id like req_<slug>, adding _2, _3... if the slug is already taken."""
    base = f"{prefix}_{slugify(label, 'entry')}"
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}_{n}", n + 1
    return candidate


def uri_for(entry_id):
    return str(LIB[entry_id])


def id_from_uri(uri):
    """The library id a URI refers to, or '' when the URI is not a library entry."""
    return uri[len(LIBRARY_NS):] if uri and uri.startswith(LIBRARY_NS) else ""
