"""Pure graph logic for starting-model provenance.

No I/O. Consumes normalized entry dicts (see smgraph.rcsb.normalize_entry) and
produces the JSON graph described in the design doc section 7.
"""

import re

# Experimental phasing methods (structure determined without a prior model).
_EXPERIMENTAL_TOKENS = (
    "SAD", "MAD", "SIR", "MIR", "ISOMORPHOUS", "ANOMALOUS",
    "AB INITIO", "AB-INITIO", "DIRECT METHOD",
    "SINGLE WAVELENGTH", "MULTIPLE WAVELENGTH", "MULTI-WAVELENGTH",
)


def classify_origin(has_parent, phasing_method):
    """Why does a structure have no *recorded* PDB starting model?

    - "derived": it does have a recorded PDB starting model (not a graph root).
    - "experimental": phased experimentally (SAD/MAD/MIR/...), a genuine root.
    - "mr_unrecorded": solved by molecular replacement, so it HAS a starting
      model, but that model is not recorded in the PDB metadata (e.g. mentioned
      only in free text). NOT a true root.
    - "unknown": no phasing method recorded, so we cannot tell. We must not
      assume it was experimentally phased.
    """
    if has_parent:
        return "derived"
    m = (phasing_method or "").upper()
    if not m:
        return "unknown"
    if "MOLECULAR REPLACEMENT" in m or re.search(r"\bMR\b", m):
        return "mr_unrecorded"
    if any(tok in m for tok in _EXPERIMENTAL_TOKENS):
        return "experimental"
    return "unknown"


def compute_generations(parents_of):
    """Longest-path depth from a root. Cycle-safe via DFS coloring.

    parents_of[id] -> list of that node's starting-model ids. Every id that
    appears as a key or inside any value list receives a generation. Roots
    (no parents) are 0. Back-edges that would form a cycle are ignored for the
    depth calculation so the function always terminates.
    """
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


def assemble_graph(entries, seed_ids, generated_utc):
    """Build the {meta, nodes, edges} JSON object from normalized entries.

    entries: {id: normalized_entry}. seed_ids: the original search set.
    generated_utc: injected timestamp (keeps this function deterministic).
    Referenced-but-absent starting models become placeholder nodes with
    ``missing: true`` so no edge is ever dangling.
    """
    seed_ids = set(seed_ids)

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
        has_parent = bool(parents_of.get(i))
        phasing = (e or {}).get("phasing_method")
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
            "phasing_method": phasing,
            "origin": classify_origin(has_parent, phasing),
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
