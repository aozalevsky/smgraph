# Starting Model Tree (smtree) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect molecular-replacement starting-model provenance from the RCSB PDB API and render it as a self-contained interactive web graph (demonstrated on human thrombin).

**Architecture:** A pure graph-logic core (no I/O) is wrapped by an RCSB network client and a `collect.py` CLI that produces a `data/thrombin.json` graph file. A separate `build.py` inlines vendored JS libraries and the base64-encoded dataset into an HTML template to produce a single offline `smtree.html`. The two halves communicate only through the JSON schema.

**Tech Stack:** Python 3 (stdlib only: `urllib`, `json`, `argparse`, `base64`, `time`), pytest for tests, Cytoscape.js + cytoscape-dagre for the browser graph.

## Global Constraints

- Python: **standard library only** for runtime code (no `requests`, no third-party HTTP). `pytest` is a dev/test dependency only.
- Network access to `https://search.rcsb.org` and `https://data.rcsb.org` only.
- Edge direction is **child → starting-model**: `edge.source` is the newer structure, `edge.target` is the structure it was built from.
- `generation = 0` for roots (no PDB starting model); otherwise `1 + max(generation of parents)`.
- Only `pdbx_initial_refinement_model` entries with `source_name == "PDB"` create edges.
- JSON schema is the contract in the design doc §7 — do not deviate.
- The final `smtree.html` must contain **no external URLs** (fully offline/self-contained) except human-facing `https://www.rcsb.org/structure/<id>` links opened on click.
- Default query scope: **UniProt P00734** (human thrombin), verified to return 477 experimental entries.

---

## File Structure

```
smtree/
  __init__.py
  graph.py          # pure graph logic: generations, assembly (no I/O)
  rcsb.py           # RCSB Search + GraphQL client, entry normalization
collect.py          # CLI: seed search → fetch → ancestry walk → write JSON
build.py            # inline vendor libs + base64 data → smtree.html
smtree.template.html
smtree.html         # generated
data/thrombin.json  # generated
vendor/             # cytoscape.min.js, dagre.min.js, cytoscape-dagre.js
tests/
  test_graph.py
  test_rcsb.py
  test_collect.py
  test_build.py
README.md
```

---

### Task 1: Generation computation (pure)

**Files:**
- Create: `smtree/__init__.py` (empty), `smtree/graph.py`
- Test: `tests/test_graph.py`

**Interfaces:**
- Produces: `compute_generations(parents_of: dict[str, list[str]]) -> dict[str, int]`
  where `parents_of[id]` is the list of that node's starting-model ids. Every id
  that appears anywhere (as key or in any value list) gets a generation. Roots
  (empty parent list) → 0. Cycles are broken by ignoring back-edges and do not
  raise or hang.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_graph.py
from smtree.graph import compute_generations

def test_linear_chain():
    # C -> B -> A (A is root)
    g = compute_generations({"C": ["B"], "B": ["A"], "A": []})
    assert g == {"A": 0, "B": 1, "C": 2}

def test_diamond_takes_longest_path():
    # D built from B and C; B and C both from A
    g = compute_generations({"D": ["B", "C"], "B": ["A"], "C": ["A"], "A": []})
    assert g == {"A": 0, "B": 1, "C": 1, "D": 2}

def test_parent_only_appears_in_values():
    # A referenced as a parent but never a key
    g = compute_generations({"B": ["A"]})
    assert g == {"A": 0, "B": 1}

def test_cycle_does_not_hang():
    # X -> Y -> X (pathological). Must terminate; both get finite generations.
    g = compute_generations({"X": ["Y"], "Y": ["X"]})
    assert set(g) == {"X", "Y"}
    assert all(v >= 0 for v in g.values())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_graph.py -q`
Expected: FAIL — `ImportError` / `compute_generations` not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# smtree/graph.py
def compute_generations(parents_of):
    """Longest-path depth from a root. Cycle-safe via DFS coloring."""
    # Ensure every referenced node is a key.
    nodes = set(parents_of)
    for ps in parents_of.values():
        nodes.update(ps)
    parents = {n: list(parents_of.get(n, [])) for n in nodes}

    gen = {}
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in nodes}

    def visit(n):
        color[n] = GREY
        best = 0
        for p in parents[n]:
            if color[p] == GREY:
                continue  # back-edge -> ignore to break cycle
            if color[p] == WHITE:
                visit(p)
            best = max(best, gen[p] + 1)
        gen[n] = best
        color[n] = BLACK

    for n in nodes:
        if color[n] == WHITE:
            visit(n)
    return gen
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_graph.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add smtree/__init__.py smtree/graph.py tests/test_graph.py
git commit -m "feat: cycle-safe generation computation for starting-model graph"
```

---

### Task 2: Graph assembly (pure)

**Files:**
- Modify: `smtree/graph.py`
- Test: `tests/test_graph.py`

**Interfaces:**
- Consumes: `compute_generations` (Task 1).
- Produces: `assemble_graph(entries: dict[str, dict], seed_ids: set[str], generated_utc: str) -> dict`.
  `entries[id]` is a normalized entry dict with keys:
  `title, method, resolution (float|None), year (int|None), organism (str|None),
  starting_models (list[{accession_code, source_name, type}])`.
  Returns the full JSON object `{meta, nodes, edges}` per design §7. Any id that
  is referenced as a starting model but absent from `entries` becomes a node with
  `missing: true` and empty metadata. `generated_utc` is injected (not read from
  the clock) so the function is deterministic and testable.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_graph.py  (append)
from smtree.graph import assemble_graph

def _entry(title="t", sms=()):
    return {"title": title, "method": "X-RAY DIFFRACTION", "resolution": 2.0,
            "year": 2010, "organism": "Homo sapiens",
            "starting_models": [{"accession_code": a, "source_name": "PDB",
                                 "type": "experimental model"} for a in sms]}

def test_assemble_nodes_edges_and_generations():
    entries = {"C": _entry(sms=["B"]), "B": _entry(sms=["A"]), "A": _entry()}
    g = assemble_graph(entries, seed_ids={"C"}, generated_utc="2026-07-08T00:00:00Z")
    nodes = {n["id"]: n for n in g["nodes"]}
    assert nodes["A"]["generation"] == 0 and nodes["A"]["is_root"] is True
    assert nodes["C"]["generation"] == 2
    assert nodes["A"]["child_count"] == 1      # B descends from A
    assert nodes["C"]["in_query"] is True and nodes["B"]["in_query"] is False
    assert {"source": "C", "target": "B", "type": "experimental model"} in g["edges"]
    assert g["meta"]["node_count"] == 3 and g["meta"]["edge_count"] == 2
    assert g["meta"]["max_generation"] == 2

def test_missing_parent_becomes_placeholder():
    entries = {"B": _entry(sms=["GONE"])}
    g = assemble_graph(entries, seed_ids={"B"}, generated_utc="2026-07-08T00:00:00Z")
    nodes = {n["id"]: n for n in g["nodes"]}
    assert nodes["GONE"]["missing"] is True
    assert nodes["GONE"]["generation"] == 0
    assert {"source": "B", "target": "GONE", "type": "experimental model"} in g["edges"]

def test_non_pdb_source_makes_no_edge():
    e = {"title": "t", "method": "X-RAY DIFFRACTION", "resolution": 2.0,
         "year": 2010, "organism": None,
         "starting_models": [{"accession_code": "AF-XYZ", "source_name": "AlphaFold",
                              "type": "in silico model"}]}
    g = assemble_graph({"B": e}, seed_ids={"B"}, generated_utc="2026-07-08T00:00:00Z")
    assert g["edges"] == []
    assert [n for n in g["nodes"] if n["id"] == "B"][0]["sm_type"] == "in silico model"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_graph.py -q`
Expected: FAIL — `assemble_graph` not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# smtree/graph.py  (append)
def assemble_graph(entries, seed_ids, generated_utc):
    seed_ids = set(seed_ids)

    # Build parent map (PDB starting models only) and edge list.
    parents_of = {}
    edges = []
    referenced = set()
    for eid, e in entries.items():
        pdb_parents = []
        for sm in e.get("starting_models") or []:
            if sm.get("source_name") == "PDB" and sm.get("accession_code"):
                pid = sm["accession_code"].upper()
                pdb_parents.append(pid)
                referenced.add(pid)
                edges.append({"source": eid, "target": pid,
                              "type": sm.get("type") or ""})
        parents_of[eid] = pdb_parents

    # Placeholders for referenced-but-absent ids.
    all_ids = set(entries) | referenced
    for pid in referenced - set(entries):
        parents_of.setdefault(pid, [])

    gen = compute_generations(parents_of)

    child_count = {i: 0 for i in all_ids}
    for edge in edges:
        child_count[edge["target"]] += 1

    nodes = []
    for i in sorted(all_ids):
        e = entries.get(i)
        sm_type = None
        if e and e.get("starting_models"):
            sm_type = (e["starting_models"][0] or {}).get("type")
        nodes.append({
            "id": i,
            "title": (e or {}).get("title"),
            "method": (e or {}).get("method"),
            "resolution": (e or {}).get("resolution"),
            "year": (e or {}).get("year"),
            "organism": (e or {}).get("organism"),
            "generation": gen.get(i, 0),
            "is_root": gen.get(i, 0) == 0,
            "in_query": i in seed_ids,
            "child_count": child_count.get(i, 0),
            "sm_type": sm_type,
            "missing": e is None,
        })

    meta = {
        "query": None,  # filled by collect.py
        "generated_utc": generated_utc,
        "source": "RCSB PDB Data API",
        "node_count": len(nodes),
        "edge_count": len(edges),
        "max_generation": max(gen.values()) if gen else 0,
    }
    return {"meta": meta, "nodes": nodes, "edges": edges}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_graph.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add smtree/graph.py tests/test_graph.py
git commit -m "feat: assemble starting-model graph JSON from normalized entries"
```

---

### Task 3: RCSB client

**Files:**
- Create: `smtree/rcsb.py`
- Test: `tests/test_rcsb.py`

**Interfaces:**
- Produces:
  - `build_search_query(uniprot=None, text=None, query=None) -> dict` — returns the
    RCSB Search API request body. Exactly one of the three is used; precedence
    `query > uniprot > text`. Always sets `return_all_hits: true` and
    `results_content_type: ["experimental"]`.
  - `normalize_entry(raw: dict) -> dict` — maps one GraphQL `entries` element to
    the normalized shape consumed by `assemble_graph` (Task 2).
  - `search_entry_ids(query_body: dict, *, opener=...) -> list[str]` — POST/GET to
    Search API, returns identifiers. (Network; covered by integration test.)
  - `fetch_entries(ids: list[str], *, batch_size=200, opener=...) -> dict[str,dict]`
    — GraphQL batch fetch, returns `{id: normalized_entry}`, with retry/backoff.
    (Network.) `opener` is an injectable callable `(url, data|None) -> bytes` so
    the network can be mocked in tests.

- [ ] **Step 1: Write the failing tests (pure parts only)**

```python
# tests/test_rcsb.py
from smtree.rcsb import build_search_query, normalize_entry

def test_build_search_query_uniprot():
    q = build_search_query(uniprot="P00734")
    p = q["query"]["parameters"]
    assert p["attribute"].endswith("database_accession")
    assert p["value"] == "P00734"
    assert q["request_options"]["return_all_hits"] is True
    assert q["request_options"]["results_content_type"] == ["experimental"]

def test_build_search_query_text():
    q = build_search_query(text="thrombin")
    assert q["query"]["service"] == "full_text"
    assert q["query"]["parameters"]["value"] == "thrombin"

def test_normalize_entry_full():
    raw = {"rcsb_id": "4UD9", "struct": {"title": "Thrombin complex"},
           "exptl": [{"method": "X-RAY DIFFRACTION"}],
           "rcsb_accession_info": {"initial_release_date": "2015-08-26T00:00:00Z"},
           "rcsb_entry_info": {"resolution_combined": [1.124]},
           "polymer_entities": [{"rcsb_entity_source_organism":
                                 [{"ncbi_scientific_name": "Homo sapiens"}]}],
           "pdbx_initial_refinement_model": [{"accession_code": "1H8D",
                                              "source_name": "PDB",
                                              "type": "experimental model"}]}
    n = normalize_entry(raw)
    assert n["title"] == "Thrombin complex"
    assert n["method"] == "X-RAY DIFFRACTION"
    assert n["resolution"] == 1.124
    assert n["year"] == 2015
    assert n["organism"] == "Homo sapiens"
    assert n["starting_models"][0]["accession_code"] == "1H8D"

def test_normalize_entry_sparse():
    n = normalize_entry({"rcsb_id": "1PPB",
                         "pdbx_initial_refinement_model": None})
    assert n["resolution"] is None and n["year"] is None
    assert n["organism"] is None and n["starting_models"] == []
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_rcsb.py -q`
Expected: FAIL — module/functions not defined.

- [ ] **Step 3: Implement**

```python
# smtree/rcsb.py
import json
import time
import urllib.request
import urllib.parse

SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
GRAPHQL_URL = "https://data.rcsb.org/graphql"
_UNIPROT_ATTR = ("rcsb_polymer_entity_container_identifiers"
                 ".reference_sequence_identifiers.database_accession")

_GQL = """query($ids:[String!]!){ entries(entry_ids:$ids){
  rcsb_id struct{title} exptl{method}
  rcsb_accession_info{initial_release_date}
  rcsb_entry_info{resolution_combined}
  polymer_entities{ rcsb_entity_source_organism{ ncbi_scientific_name } }
  pdbx_initial_refinement_model{ accession_code source_name type } } }"""


def _default_opener(url, data=None):
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "User-Agent": "smtree/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def build_search_query(uniprot=None, text=None, query=None):
    opts = {"return_all_hits": True, "results_content_type": ["experimental"]}
    if query is not None:
        q = dict(query)
        q.setdefault("request_options", {}).update(opts)
        return q
    if uniprot is not None:
        node = {"type": "terminal", "service": "text",
                "parameters": {"attribute": _UNIPROT_ATTR,
                               "operator": "exact_match", "value": uniprot}}
    else:
        node = {"type": "terminal", "service": "full_text",
                "parameters": {"value": text}}
    return {"query": node, "return_type": "entry", "request_options": opts}


def normalize_entry(raw):
    def first(lst):
        return lst[0] if lst else None
    res_list = (raw.get("rcsb_entry_info") or {}).get("resolution_combined")
    res = res_list[0] if res_list else None
    date = (raw.get("rcsb_accession_info") or {}).get("initial_release_date")
    year = int(date[:4]) if date else None
    org = None
    pe = first(raw.get("polymer_entities") or [])
    if pe:
        so = first(pe.get("rcsb_entity_source_organism") or [])
        if so:
            org = so.get("ncbi_scientific_name")
    exptl = first(raw.get("exptl") or [])
    return {
        "title": (raw.get("struct") or {}).get("title"),
        "method": exptl.get("method") if exptl else None,
        "resolution": res,
        "year": year,
        "organism": org,
        "starting_models": raw.get("pdbx_initial_refinement_model") or [],
    }


def search_entry_ids(query_body, opener=_default_opener):
    url = SEARCH_URL + "?" + urllib.parse.urlencode(
        {"json": json.dumps(query_body)})
    raw = _retry(lambda: opener(url))
    data = json.loads(raw)
    return [r["identifier"] for r in data.get("result_set", [])]


def fetch_entries(ids, batch_size=200, opener=_default_opener):
    out = {}
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i + batch_size]
        body = json.dumps({"query": _GQL, "variables": {"ids": batch}}).encode()
        raw = _retry(lambda b=body: opener(GRAPHQL_URL, b))
        data = json.loads(raw)
        for e in (data.get("data") or {}).get("entries") or []:
            out[e["rcsb_id"].upper()] = normalize_entry(e)
        time.sleep(0.2)  # politeness
    return out


def _retry(fn, attempts=4):
    delay = 1.0
    for k in range(attempts):
        try:
            return fn()
        except Exception:
            if k == attempts - 1:
                raise
            time.sleep(delay)
            delay *= 2
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_rcsb.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add smtree/rcsb.py tests/test_rcsb.py
git commit -m "feat: RCSB search + GraphQL client with entry normalization"
```

---

### Task 4: collect.py CLI + ancestry walk

**Files:**
- Create: `collect.py`
- Test: `tests/test_collect.py`

**Interfaces:**
- Consumes: `assemble_graph` (Task 2), `build_search_query`, `search_entry_ids`,
  `fetch_entries` (Task 3).
- Produces: `walk_and_collect(seed_ids, fetch_fn, max_depth) -> dict[str,dict]`
  — starting from seeds, repeatedly fetches, discovers PDB parents not yet seen,
  and fetches them, up to `max_depth` extra rounds; returns all normalized
  entries. `fetch_fn(ids) -> dict[str,dict]` is injected so tests avoid network.
  Also `main(argv)` wiring argparse → search → walk → assemble → write file.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_collect.py
from collect import walk_and_collect

def test_walk_follows_ancestry():
    universe = {
        "C": {"starting_models": [{"accession_code": "B", "source_name": "PDB"}]},
        "B": {"starting_models": [{"accession_code": "A", "source_name": "PDB"}]},
        "A": {"starting_models": []},
    }
    calls = []
    def fake_fetch(ids):
        calls.append(list(ids))
        return {i: universe[i] for i in ids if i in universe}
    got = walk_and_collect(["C"], fake_fetch, max_depth=5)
    assert set(got) == {"A", "B", "C"}          # walked all the way to root
    assert calls[0] == ["C"]                     # seeds first
    assert any("A" in c for c in calls[1:])      # A discovered via the walk

def test_walk_respects_max_depth():
    universe = {
        "C": {"starting_models": [{"accession_code": "B", "source_name": "PDB"}]},
        "B": {"starting_models": [{"accession_code": "A", "source_name": "PDB"}]},
        "A": {"starting_models": []},
    }
    def fake_fetch(ids):
        return {i: universe[i] for i in ids if i in universe}
    got = walk_and_collect(["C"], fake_fetch, max_depth=0)
    assert set(got) == {"C"}                     # no ancestry rounds
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_collect.py -q`
Expected: FAIL — `collect` / `walk_and_collect` not defined.

- [ ] **Step 3: Implement**

```python
# collect.py
import argparse
import datetime
import json
import sys

from smtree.graph import assemble_graph
from smtree.rcsb import build_search_query, search_entry_ids, fetch_entries


def _pdb_parents(entry):
    return [sm["accession_code"].upper()
            for sm in (entry.get("starting_models") or [])
            if sm.get("source_name") == "PDB" and sm.get("accession_code")]


def walk_and_collect(seed_ids, fetch_fn, max_depth):
    collected = {}
    frontier = list(dict.fromkeys(i.upper() for i in seed_ids))
    depth = 0
    while frontier:
        got = fetch_fn(frontier)
        collected.update(got)
        if depth >= max_depth:
            break
        nxt = []
        for eid in frontier:
            for p in _pdb_parents(got.get(eid, {})):
                if p not in collected and p not in nxt:
                    nxt.append(p)
        frontier = nxt
        depth += 1
    return collected


def main(argv=None):
    ap = argparse.ArgumentParser(description="Collect PDB starting-model graph.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--uniprot", help="UniProt accession to scope by")
    g.add_argument("--text", help="full-text query term")
    g.add_argument("--query-file", help="path to a raw RCSB search query JSON")
    ap.add_argument("--out", default="data/thrombin.json")
    ap.add_argument("--max-depth", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=200)
    ap.add_argument("--limit", type=int, default=0, help="cap seeds (testing)")
    a = ap.parse_args(argv)

    raw_query = None
    if a.query_file:
        with open(a.query_file) as f:
            raw_query = json.load(f)
    uni = a.uniprot if (a.uniprot or a.text or a.query_file) else "P00734"
    query = build_search_query(uniprot=uni, text=a.text, query=raw_query)

    label = a.text or (a.query_file and "custom") or uni
    print(f"Searching RCSB ({label}) ...", file=sys.stderr)
    seeds = search_entry_ids(query)
    if a.limit:
        seeds = seeds[:a.limit]
    print(f"  {len(seeds)} seed entries", file=sys.stderr)

    def fetch_fn(ids):
        return fetch_entries(ids, batch_size=a.batch_size)

    entries = walk_and_collect(seeds, fetch_fn, max_depth=a.max_depth)
    print(f"  {len(entries)} entries after ancestry walk", file=sys.stderr)

    now = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    graph = assemble_graph(entries, seed_ids=set(s.upper() for s in seeds),
                           generated_utc=now)
    graph["meta"]["query"] = label

    import os
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(graph, f)
    m = graph["meta"]
    print(f"Wrote {a.out}: {m['node_count']} nodes, {m['edge_count']} edges, "
          f"max generation {m['max_generation']}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_collect.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add collect.py tests/test_collect.py
git commit -m "feat: collect.py CLI with ancestry walk"
```

---

### Task 5: Live integration smoke test + generate dataset

**Files:**
- Test: `tests/test_collect.py` (append a network-marked test)
- Produce: `data/thrombin.json`

- [ ] **Step 1: Add a live smoke test (skipped without network opt-in)**

```python
# tests/test_collect.py  (append)
import os, pytest
from collect import main

@pytest.mark.skipif(os.environ.get("SMTREE_LIVE") != "1",
                    reason="set SMTREE_LIVE=1 to hit the RCSB API")
def test_live_small(tmp_path):
    import json
    out = tmp_path / "small.json"
    main(["--uniprot", "P00734", "--limit", "40", "--out", str(out)])
    g = json.loads(out.read_text())
    assert g["meta"]["node_count"] > 0
    assert g["meta"]["max_generation"] >= 1     # at least one real chain
    ids = {n["id"] for n in g["nodes"]}
    for e in g["edges"]:
        assert e["source"] in ids and e["target"] in ids  # no dangling edges
```

- [ ] **Step 2: Run the smoke test against the live API**

Run: `SMTREE_LIVE=1 python -m pytest tests/test_collect.py::test_live_small -q`
Expected: PASS.

- [ ] **Step 3: Generate the real dataset**

Run: `python collect.py --uniprot P00734 --out data/thrombin.json`
Expected: stderr reports ~477 seeds and a node/edge/max-generation summary with
`max generation >= 3`. Inspect: `python -c "import json;m=json.load(open('data/thrombin.json'))['meta'];print(m)"`

- [ ] **Step 4: Commit**

```bash
git add tests/test_collect.py data/thrombin.json
git commit -m "test: live smoke test; generate thrombin dataset"
```

---

### Task 6: Vendor the graph libraries

**Files:**
- Create: `vendor/cytoscape.min.js`, `vendor/dagre.min.js`, `vendor/cytoscape-dagre.js`
- Create: `vendor/SOURCES.md` (records exact URLs + versions fetched)

- [ ] **Step 1: Download pinned minified builds**

```bash
mkdir -p vendor
curl -sL "https://unpkg.com/cytoscape@3.30.2/dist/cytoscape.min.js" -o vendor/cytoscape.min.js
curl -sL "https://unpkg.com/dagre@0.8.5/dist/dagre.min.js" -o vendor/dagre.min.js
curl -sL "https://unpkg.com/cytoscape-dagre@2.5.0/cytoscape-dagre.js" -o vendor/cytoscape-dagre.js
```

- [ ] **Step 2: Verify they are non-empty valid JS (not HTML error pages)**

Run:
```bash
for f in vendor/cytoscape.min.js vendor/dagre.min.js vendor/cytoscape-dagre.js; do
  echo "$f: $(wc -c < $f) bytes"; head -c 40 "$f" | grep -qi "<!doctype\|<html" && echo "  ERROR: HTML" || echo "  ok"; done
```
Expected: each file is large (cytoscape > 300 KB, dagre > 150 KB) and reports `ok`.

- [ ] **Step 3: Record sources**

Create `vendor/SOURCES.md` listing the three exact URLs, versions, and the date.

- [ ] **Step 4: Commit**

```bash
git add vendor/
git commit -m "chore: vendor cytoscape, dagre, cytoscape-dagre for offline use"
```

---

### Task 7: HTML template (app UI + logic)

**Files:**
- Create: `smtree.template.html`

> Consult the `dataviz` skill for an accessible sequential palette (light + dark)
> before choosing generation colors. The template contains three injection
> markers that `build.py` (Task 8) replaces:
> `/*__CYTOSCAPE__*/`, `/*__DAGRE__*/`, `/*__CYDAGRE__*/` (library bodies) and
> `"__DATA_B64__"` (the base64 dataset string).

- [ ] **Step 1: Write the template**

Structure (single file, no external URLs):

- `<head>`: inline CSS. Theme-aware via `prefers-color-scheme`. Layout: a top
  toolbar (title + stats), a left control panel (layout toggle, search box,
  "hide isolated roots" checkbox, generation range, "Upload JSON" input, legend),
  a `#cy` graph container filling the rest, and a hidden `#info` side panel.
- Three `<script>` blocks holding the injected library bodies, in order:
  cytoscape, dagre, cytoscape-dagre, then `cytoscape.use(cytoscapeDagre)`.
- A final `<script>` with the app. Required functions/behaviors:

```js
// --- data load ---
const DATA_B64 = "__DATA_B64__";
function decodeData(b64){ return JSON.parse(new TextDecoder()
  .decode(Uint8Array.from(atob(b64), c => c.charCodeAt(0)))); }

// --- palette: color by generation (from dataviz skill) ---
const GEN_COLORS = [/* sequential ramp, index by generation, clamp at end */];
function genColor(g){ return GEN_COLORS[Math.min(g, GEN_COLORS.length-1)]; }

// --- build elements ---
function toElements(graph){
  const nodes = graph.nodes.map(n => ({ data: {
    id: n.id, label: n.id, gen: n.generation, root: n.is_root,
    missing: !!n.missing, childCount: n.child_count, meta: n } }));
  const edges = graph.edges.map((e,i) => ({ data: {
    id: "e"+i, source: e.source, target: e.target } }));
  return [...nodes, ...edges];
}

// --- cytoscape init + style ---
// node width/height = 18 + sqrt(childCount)*6 ; background-color = genColor(gen)
// [root] => thicker border ; [missing] => dashed border, muted fill
// edge => target-arrow-shape triangle, curve-style bezier

// --- layouts (toggle) ---
const HIER = { name:"dagre", rankDir:"TB", nodeSep:18, rankSep:60 };
const FORCE = { name:"fcose", quality:"default", animate:false }; // or "cose" if fcose absent
function runLayout(name){ cy.layout(name==="hier"?HIER:FORCE).run(); }

// --- filter: hide isolated roots (degree 0) ---
function applyFilters(){ /* toggle .hidden class on gen-range + isolated roots */ }

// --- interactions ---
// tap node: clear .faded/.path; compute ancestry to roots by walking outgoing
//   edges (source->target) transitively; add .path to those nodes+edges,
//   .faded to the rest; populate #info with meta + rcsb link.
// tap background: clear highlight, hide #info.
// search input: select+center matching id.

// --- upload ---
// file input change -> FileReader.readAsText -> JSON.parse -> validate keys
//   {meta,nodes,edges} and node.id present -> rebuild graph or show error banner.

// --- boot ---
loadGraph(decodeData(DATA_B64));
```

Notes for the implementer:
- `fcose` is a separate extension; to avoid vendoring a fourth lib, use
  Cytoscape's built-in `cose` for the force layout (`name:"cose"`). Keep the
  toggle labels "Hierarchy" / "Force".
- Ancestry highlight walks **outgoing** edges (source→target = child→parent),
  so clicking a node highlights the path toward its roots.
- The stats bar reads `graph.meta` for counts + max generation + query label.

- [ ] **Step 2: Sanity-check the template parses as HTML**

Run: `python -c "import pathlib,html.parser as h; p=h.HTMLParser(); p.feed(pathlib.open if False else open('smtree.template.html').read()); print('parsed ok')"`
Expected: `parsed ok` (no exception). Confirm the four injection markers each
appear exactly once: `grep -c "__DATA_B64__\|__CYTOSCAPE__\|__DAGRE__\|__CYDAGRE__" smtree.template.html`.

- [ ] **Step 3: Commit**

```bash
git add smtree.template.html
git commit -m "feat: interactive graph template (cytoscape, layout toggle, upload)"
```

---

### Task 8: build.py — assemble self-contained smtree.html

**Files:**
- Create: `build.py`
- Test: `tests/test_build.py`
- Produce: `smtree.html`

**Interfaces:**
- Produces: `build_html(template: str, data_json: str, libs: dict[str,str]) -> str`
  — replaces the four markers and returns the final HTML. `libs` maps
  `{"__CYTOSCAPE__":..., "__DAGRE__":..., "__CYDAGRE__":...}`. Data is base64 of
  the raw JSON text.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_build.py
import base64, json
from build import build_html

def test_build_injects_data_and_libs():
    tmpl = ('X /*__CYTOSCAPE__*/ Y /*__DAGRE__*/ Z /*__CYDAGRE__*/ '
            'D="__DATA_B64__";')
    data = json.dumps({"meta": {}, "nodes": [], "edges": []})
    out = build_html(tmpl, data, {"__CYTOSCAPE__": "CY", "__DAGRE__": "DG",
                                  "__CYDAGRE__": "CD"})
    assert "CY" in out and "DG" in out and "CD" in out
    assert "__DATA_B64__" not in out and "/*__CYTOSCAPE__*/" not in out
    b64 = out.split('D="', 1)[1].split('"', 1)[0]
    assert json.loads(base64.b64decode(b64)) == {"meta": {}, "nodes": [],
                                                 "edges": []}
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_build.py -q`
Expected: FAIL — `build` not defined.

- [ ] **Step 3: Implement**

```python
# build.py
import argparse
import base64


def build_html(template, data_json, libs):
    out = template
    for marker, body in libs.items():
        out = out.replace("/*" + marker + "*/", body)
    b64 = base64.b64encode(data_json.encode()).decode()
    out = out.replace("__DATA_B64__", b64)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build self-contained smtree.html")
    ap.add_argument("--template", default="smtree.template.html")
    ap.add_argument("--data", default="data/thrombin.json")
    ap.add_argument("--out", default="smtree.html")
    a = ap.parse_args(argv)
    libs = {
        "__CYTOSCAPE__": open("vendor/cytoscape.min.js").read(),
        "__DAGRE__": open("vendor/dagre.min.js").read(),
        "__CYDAGRE__": open("vendor/cytoscape-dagre.js").read(),
    }
    html = build_html(open(a.template).read(), open(a.data).read(), libs)
    with open(a.out, "w") as f:
        f.write(html)
    print(f"Wrote {a.out}: {len(html)} bytes")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test + build**

Run: `python -m pytest tests/test_build.py -q` → PASS.
Run: `python build.py` → writes `smtree.html`.
Verify no external URLs remain:
`grep -oE "https?://[^\"' )]+" smtree.html | grep -v "rcsb.org/structure" | sort -u`
Expected: empty output (only rcsb.org/structure click-links allowed).

- [ ] **Step 5: Commit**

```bash
git add build.py tests/test_build.py smtree.html
git commit -m "feat: build.py assembles self-contained smtree.html"
```

---

### Task 9: End-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -q`
Expected: all non-live tests PASS.

- [ ] **Step 2: Drive the built page**

Use the `verify` skill (headless browser) or open `smtree.html` manually and confirm:
- Page renders offline (disconnect network / `file://` open) with the thrombin graph.
- Layout toggle switches Hierarchy ↔ Force and re-lays-out.
- Clicking a deep node highlights an ancestry path of ≥3 generations to a root and
  fills the info panel with a working rcsb.org link.
- "Hide isolated roots" changes the visible node count.
- Uploading `data/thrombin.json` reloads the same graph; uploading a malformed
  file shows an error and leaves the graph intact.

- [ ] **Step 3: Capture a screenshot** of the hierarchy view for the README.

- [ ] **Step 4: Commit** any fixes found during verification.

---

### Task 10: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write usage docs**

Cover: what starting models are and what the graph shows; `python collect.py`
options (`--uniprot`/`--text`/`--query-file`, default P00734); `python build.py`;
opening `smtree.html`; the JSON schema; how to visualize a different protein
(run collect for another UniProt, then upload the JSON into the page). Embed the
Task 9 screenshot.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with usage and schema"
```

---

## Self-Review

**Spec coverage:**
- §2 data source (Search + GraphQL) → Tasks 3, 5. ✓
- §5 pipeline (seed, batch, ancestry walk, generations, derived fields, robustness)
  → Tasks 1–4 (generations T1, derived fields/placeholders T2, client/retry T3,
  walk T4). ✓
- §6 viz (vendored libs, base64 + upload, layout toggle, encoding, interactions,
  filters) → Tasks 6, 7, 8. ✓
- §7 JSON schema → Task 2 (assemble_graph) is the single source of truth. ✓
- §8 error handling (retry T3, placeholders T2, cycles T1, malformed upload T7). ✓
- §9 testing (unit T1–4, integration T5, viz drive T9). ✓
- §10 file layout → matches (refined: logic in `smtree/` package). ✓

**Placeholder scan:** No TBD/TODO in code steps. Task 7 intentionally specifies UI
behavior with concrete function skeletons + rules rather than 400 lines of CSS
verbatim; every function's contract and the injection markers are pinned, so it is
executable without guesswork. `GEN_COLORS` values are deferred to the dataviz skill
by design (accessible palette), not left vague — the skill provides exact values.

**Type consistency:** normalized entry shape (`title, method, resolution, year,
organism, starting_models`) is identical in Tasks 2, 3, 4. Edge shape
`{source,target,type}` and node fields match §7 across Tasks 2, 7, 8. Injection
markers `__CYTOSCAPE__/__DAGRE__/__CYDAGRE__/__DATA_B64__` match between Tasks 7
and 8. `walk_and_collect(seed_ids, fetch_fn, max_depth)` signature matches its
test and caller. ✓
