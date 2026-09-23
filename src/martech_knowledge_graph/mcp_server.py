"""
MCP server exposing the martech knowledge graph to LLMs/agents.

Two tools, per the "single doorway" principle from the original handoff
doc: run_sparql (read the graph) and get_ontology_schema (understand its
shape well enough to write correct queries against it). Both reuse
graph_explorer.py directly -- no new query engine, no duplicated
extraction logic.

Read-only by construction, not by filtering: only Graph.query() is ever
called, never Graph.update(). rdflib parses .query() input against the
SPARQL *Query* grammar only (SELECT/ASK/CONSTRUCT/DESCRIBE) -- an
INSERT/DELETE string fails to parse rather than executing, so there is no
separate "reject write queries" check to get wrong.

Runs as a second, independent process alongside `martech-knowledge-graph
serve` (Flask is WSGI, FastMCP's HTTP transport is ASGI -- simplest to
keep them separate rather than force one process to host both). It reads
the same --data-dir and the same .mkg-mode marker file server.py writes,
so switching demo/org mode in the browser is reflected on the very next
tool call, without restarting this process.

Run via the CLI:
    martech-knowledge-graph mcp
"""

from pathlib import Path

from fastmcp import FastMCP

from . import graph_explorer as ge
from .workspace import resolve_active_dir


def _serialize_results(results):
    """rdflib SPARQLResult -> a JSON *object* (MCP's structuredContent must be
    an object, not a bare array/bool -- a bare list return value falls back
    to plain-text content client-side instead of structured data, so every
    branch here wraps its payload in a dict).

    .type distinguishes the four query forms -- ASK's result object isn't a
    plain bool (it's a SPARQLResult with .type == "ASK" that happens to be
    truthy/iterable), so it needs its own branch rather than an isinstance
    check.
    """
    if results.type == "ASK":
        return {"result": bool(results)}

    if results.type == "SELECT":
        rows = [
            {str(k): str(v) for k, v in row.asdict().items() if v is not None}
            for row in results
        ]
        return {"results": rows}

    # CONSTRUCT / DESCRIBE: each row is a (subject, predicate, object) triple.
    rows = [
        {"subject": str(s), "predicate": str(p), "object": str(o)}
        for s, p, o in results
    ]
    return {"results": rows}


def create_mcp(data_dir: Path) -> FastMCP:
    """Build the FastMCP server, bound to a specific --data-dir (org workspace)."""
    data_dir = Path(data_dir)
    mcp = FastMCP("Martech Knowledge Graph")

    def load_active_graph():
        active_dir = resolve_active_dir(data_dir, ge.EXAMPLES_DIR)
        return ge.load_graph(ontology_path=ge.ONTOLOGY_FILE, script_dir=active_dir)

    @mcp.tool
    def run_sparql(query: str) -> dict:
        """Run a read-only SPARQL query (SELECT, ASK, CONSTRUCT, or DESCRIBE) against the
        martech knowledge graph -- components (metrics/dimensions) with their curated business
        context, journeys, stages, KPIs, and requirements. Call get_ontology_schema first if
        you're not sure what classes and properties are available. Write operations (INSERT,
        DELETE) are not supported -- this tool is read-only.

        Returns {"results": [...]} for SELECT/CONSTRUCT/DESCRIBE (a list of variable-binding or
        subject/predicate/object dicts), {"result": true|false} for ASK, or {"error": "..."} if
        the query is invalid."""
        g = load_active_graph()
        try:
            results = g.query(query)
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}
        return _serialize_results(results)

    @mcp.tool
    def get_ontology_schema() -> dict:
        """Return the martech knowledge graph's ontology: every class and property, with what
        it means (comment) and, for properties, their domain/range. Call this before
        run_sparql if you don't already know the graph's shape.

        Returns {"classes": [{"name", "comment"}, ...], "properties": [{"name", "domain",
        "range", "comment"}, ...]}."""
        g = load_active_graph()
        return ge.extract_ontology_schema(g)

    return mcp
