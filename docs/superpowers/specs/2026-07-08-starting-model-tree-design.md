# Starting Model Tree (smtree) — Design

**Date:** 2026-07-08
**Status:** Approved (design), pending implementation plan

## 1. Purpose

When a macromolecular structure is solved by molecular replacement (MR), it is
built starting from a previously-solved structure — its *starting model*. The
PDB records this provenance in the mmCIF category `pdbx_initial_refinement_model`.
Chaining these relationships produces a directed graph: structure → the structure
it was built from → *its* starting model, and so on back to structures that were
phased experimentally (the roots).

This project:

1. Collects starting-model provenance from the **RCSB PDB API** for a set of
   structures (default: thrombin), including full ancestry.
2. Renders it as an **interactive web graph** that shows the generations of
   models — a "family tree" of structures.

Thrombin is the demonstration case: ~2,600 thrombin entries reference a PDB
starting model, forming real multi-generational chains.

## 2. Data source

Two public RCSB endpoints, no authentication required:

- **Search API** — `https://search.rcsb.org/rcsbsearch/v2/query`
  Used to enumerate the entry set (e.g. full-text "thrombin").
- **Data API (GraphQL)** — `https://data.rcsb.org/graphql`
  Used to batch-fetch, for each entry: `pdbx_initial_refinement_model`
  (`accession_code`, `source_name`, `type`) plus display metadata (title,
  method, resolution, release year, organism).

An edge is created for every `pdbx_initial_refinement_model` whose
`source_name == "PDB"`; the edge points from the child structure to the
`accession_code` (its starting model). Non-PDB sources (AlphaFold, "in silico
model", etc.) are recorded on the node but do not create graph edges to a PDB
node, because their accession is not a PDB entry.

## 3. Scope

- **In:** the complete thrombin set and the full ancestry of every structure in
  it (ancestors are included even if not themselves tagged "thrombin"). No nodes
  are dropped from the dataset. The default *view* hides isolated roots for
  legibility; UI filters reveal everything.
- **Out (this iteration):** whole-PDB collection, non-PDB starting-model
  resolution, incremental/streaming updates. The pipeline is written so it can
  be pointed at any query later, but running all-PDB is not part of this build.

## 4. Architecture

Two decoupled components joined by a JSON file:

```
collect.py  ──►  data/thrombin.json  ──►  build.py  ──►  smtree.html
(RCSB API)       (graph: nodes+edges)     (+ vendor/)     (self-contained page)
```

- `collect.py` knows only about RCSB and the JSON schema. It has no knowledge of
  the visualization.
- `smtree.html` knows only about the JSON schema. It has no knowledge of RCSB.
- `build.py` is a thin assembler: it inlines the vendored graph libraries and the
  base64-encoded dataset into an HTML template to produce the final
  self-contained `smtree.html`.

This separation means either side can change independently, and the same JSON can
be produced by another tool and uploaded into the page.

## 5. Component 1 — Data pipeline (`collect.py`)

**CLI:** `python collect.py --query thrombin --out data/thrombin.json`
(`--query` accepts an RCSB full-text term; other flags: `--max-depth` for the
ancestry walk, `--batch-size`, `--limit` for testing.)

**Algorithm:**

1. **Seed set.** Search API returns all entry IDs matching the query.
2. **Batch fetch.** GraphQL fetches metadata + `pdbx_initial_refinement_model`
   for the seed IDs in batches (default 200), with retry-with-backoff on
   transient HTTP errors and a small inter-request delay.
3. **Ancestry walk.** Collect every referenced PDB `accession_code` not yet
   fetched; fetch those; repeat until no new IDs appear or `--max-depth` is hit.
   This pulls in ancestors outside the query set so chains reach their roots.
4. **Assemble nodes/edges.** One node per fetched entry. One edge child→parent
   per PDB starting model.
5. **Generations.** `generation(n) = 0` if the node has no PDB starting model
   (a root); otherwise `1 + max(generation(parent))`. Computed by memoized DFS
   over parents with cycle detection — if a back-edge would form a cycle it is
   ignored for the generation calc (and logged), so provenance loops cannot hang
   the pipeline.
6. **Derived fields.** `child_count` = number of structures that used this node
   as a starting model (in-degree of the child→parent edges). `is_root` =
   generation 0. `in_query` = present in the original seed set.
7. **Write JSON.**

**Robustness:** unresolvable referenced IDs (obsolete/withdrawn entries returned
as null by GraphQL) become minimal placeholder nodes flagged `missing: true` so
edges are never dangling. All network access is retried; a final failure aborts
with a clear message rather than writing a partial file.

## 6. Component 2 — Visualization (`smtree.html` via `build.py`)

**Libraries (vendored, inlined, offline):** Cytoscape.js core +
cytoscape-dagre (+ dagre). Dagre provides a layered DAG layout — correct here
because provenance is a DAG (shared parents; a structure may list multiple
starting models), not a strict tree.

**Data loading:** the thrombin dataset is embedded as a base64 string and decoded
at startup. An **"Upload JSON"** control replaces the graph with any file that
matches the schema (§7), so the page is a general viewer, not just a thrombin
demo. A schema check on upload reports mismatches instead of failing silently.

**Layouts (toggle):**
- *Generational hierarchy* — dagre, top-to-bottom, one rank per generation
  (roots at the top). Makes ancestry depth explicit.
- *Force-directed* — fcose (Cytoscape's force layout). Surfaces hubs and
  families; generation depth is de-emphasized.

**Visual encoding:**
- Node fill = generation (sequential palette + legend; consult the `dataviz`
  skill for accessible light/dark palettes).
- Node size = `child_count` (how many structures descend from it — influence).
- Roots styled distinctly (e.g. heavier border).

**Interactions:**
- Click a node → highlight its full ancestry path to a root; open an info panel
  (title, method, resolution, year, organism, starting-model type) with a link to
  `https://www.rcsb.org/structure/<id>`.
- Search box → locate/zoom a PDB ID.
- Filters → "hide isolated roots" (default on), and a generation range control.
- Header → node count, edge count, deepest generation, current query.

**Performance:** thrombin is a few thousand nodes; Cytoscape handles this. The
hide-isolated-roots default keeps the first paint legible.

## 7. JSON schema (contract between the two components)

```json
{
  "meta": {
    "query": "thrombin",
    "generated_utc": "2026-07-08T00:00:00Z",
    "source": "RCSB PDB Data API",
    "node_count": 0,
    "edge_count": 0,
    "max_generation": 0
  },
  "nodes": [
    {
      "id": "3N99",
      "title": "Crystal structure of TM1086",
      "method": "X-RAY DIFFRACTION",
      "resolution": 1.9,
      "year": 2010,
      "organism": "Homo sapiens",
      "generation": 2,
      "is_root": false,
      "in_query": true,
      "child_count": 0,
      "sm_type": "experimental model",
      "missing": false
    }
  ],
  "edges": [
    { "source": "3N99", "target": "3DCL", "type": "experimental model" }
  ]
}
```

`source` is the child; `target` is its starting model. Any node referenced by an
edge is guaranteed present in `nodes` (as a placeholder if `missing`).

## 8. Error handling

- **Network:** retry with exponential backoff on 5xx / timeouts; abort with a
  clear message after a small number of attempts (default 4). Never write a
  partial output file.
- **Missing/obsolete entries:** placeholder node, `missing: true`; edges stay
  valid.
- **Cycles in provenance:** detected during generation calc; the offending
  back-edge is ignored for ranking and logged. The edge is still shown in the
  graph.
- **Upload of malformed JSON:** the page validates required keys/shape and shows
  an error banner; the current graph is left intact.

## 9. Testing / verification

- **Pipeline unit tests:** generation computation (linear chain, diamond/shared
  parent, cycle), edge construction, placeholder creation — run against small
  hand-built fixtures, no network.
- **Pipeline integration smoke test:** `--query thrombin --limit 50` hits the
  live API and asserts a well-formed JSON with ≥1 multi-generation chain.
- **Viz verification:** open the built `smtree.html`, confirm it renders offline,
  both layouts work, click-to-highlight-ancestry works, and an uploaded JSON
  replaces the graph. Verified by driving the page (per the `verify`/`run`
  skills), not just by inspection.

## 10. File layout

```
smtree/
  collect.py                 # RCSB → data/thrombin.json
  build.py                   # template + vendor/ + base64 data → smtree.html
  smtree.template.html       # HTML/CSS/JS with injection placeholders
  smtree.html                # generated, self-contained deliverable
  data/thrombin.json         # generated dataset
  vendor/                    # downloaded minified libs (cytoscape, dagre, cy-dagre)
  tests/                     # pipeline unit tests + fixtures
  README.md
  docs/superpowers/specs/2026-07-08-starting-model-tree-design.md
```

## 11. Out of scope / future

- Whole-PDB collection and a searchable global graph.
- Resolving non-PDB starting models (AlphaFold, etc.) as first-class nodes.
- Server-backed live queries from the page.
- Timeline / temporal-layout view (generation vs. release year).
