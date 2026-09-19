# Platform MVP handoff — context layer maintenance app

## What this is
A web app for maintaining the martech knowledge graph — pull components from CJA, add business context (definition/caveats/context/owner) via a form, author journeys, generate the turtle instance data automatically from the shared ontology, view the graph live, and eventually serve it through a new MCP for LLM/agent queries.

## Vision (as stated, for reference)
A modern, easy-to-use platform: pulls components from CJA, lets you add context via a form/process for a journey or component, builds the knowledge graph and network viewer in the background based on the ontology, and ultimately exposes the graph through a new MCP.

## Scoping decisions already made — don't re-litigate these
- **MVP means "correct," not "polished."** Prove the full loop works end to end (pull component → add context → generate turtle → see it in the graph → query it) before investing in UX/design polish.
- **Component gets a form. Journey does not, yet.** Component is flat and frequent — genuinely form-shaped. Journey is compound and rare (Requirement + KPI + several Stages + Measurements) — keep Journey authoring on the existing CSV/`journey_builder.py` path (already built, already validated byte-identical against hand-written turtle) rather than building a Journey wizard now. Revisit only if real usage shows the CSV genuinely isn't enough.
- **Build the MCP last, not in parallel.** It's the one piece here with no existing implementation to adapt — sequence it after the authoring loop itself is trusted.
- **No dedicated graph DB yet** — flat `.ttl` files remain the storage layer (locked decision, carried over from the knowledge graph work). Revisit only once multi-hop query complexity or concurrent writes actually justify it.
- **Reference Adobe's native AEP/CJA graph by pointer, never duplicate it** — same `Component.refs` pattern already in the ontology.
- **Single-doorway MCP principle** — one query interface (e.g. `run_sparql` + a documentation/ontology tool), not multiple competing tools that could give contradictory answers to the same question.

## What already exists to reuse (bring these files into the new chat)
| Piece | Reuse from | New work needed |
|---|---|---|
| Pull components from CJA | Existing CJA Semantic Layer MCP | Wire into a live UI instead of manual upload |
| Component context form | — | The actual new UI piece |
| Journey authoring | `journey_builder.py` (CSV path) | Maybe a simple upload/paste UI over the same logic |
| Turtle generation | `journey_builder.py` + `martech-ontology.ttl` | None — already correct, already validated |
| Graph storage | Flat `.ttl` files | Persist wherever the app runs, still files |
| Network viewer | `graph_network.html` / `vis-network` pattern | Embed live instead of regenerating a static file |
| MCP | The `run_sparql` pattern already scoped conceptually | Build and deploy for real — genuinely new |

Files to bring in: `martech-ontology.ttl`, `journey_builder.py`, `graph_explorer.py` (for the viewer logic to adapt), `README.md`.

## Immediate next step
Scope the actual tech stack and architecture for the app — this is likely a Claude Code project given the sustained engineering involved, not a chat-based build.
