---
name: martech-kg
description: Use when the user asks about the martech / customer experience knowledge graph: customer journeys and their stages, KPIs and the requirements behind them, the components (metrics and dimensions) that measure them, data layer variables, and component definitions, caveats and owners. Also use to trace a KPI back to its tracking, or to check what a component or data layer variable feeds.
---

# Martech knowledge graph

The files in `references/` are the source of truth. Do not answer from general knowledge about what a component means in this organization.

## How to use it

1. Read `references/context-snapshot.md` first. It has precomputed chains per journey and the generation date.
2. For detail the snapshot lacks, read `references/martech-ontology.ttl` (the schema; every class and predicate has a comment) and the `references/*-instances.ttl` files (the data).
3. When you answer about the current state, state the snapshot date.

## Model in brief

- Requirement `addressed_by` KPI.
- Journey `has_stage` Stage. Stage `rolls_up_to` KPI (only the terminal stage does).
- A Measurement node links a Stage (`measured_entity`) to a Component (`measured_component`), with an optional `filter_value` when several stages share one component, such as a page-name dimension.
- DataLayerVariable `maps_to` Component.
- Component `refs` points to the platform's own schema entry. It is a pointer, not a copy.

## Rules

- Whenever you cite a component, include its caveats and owner if present.
- Separate what the graph says from what you infer, and label inferences as such.
- If something is not in the files, say it is not in the graph. Do not guess.
- The graph is read-only for you. Never imply you changed it.

## Known gaps, mention them when relevant

- KPI formulas are plain text. Inputs such as a denominator are not linked as edges, so "what depends on this component" under-reports formula inputs.
- Only the final stage of a journey rolls up to the KPI.
- The `refs` URIs contain a placeholder sandbox segment (`SANDBOX_NAME`).
