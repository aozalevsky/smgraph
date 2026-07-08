"""CLI: collect PDB starting-model provenance into a graph JSON file.

Search the RCSB PDB for a set of entries, batch-fetch their metadata and
starting-model references, walk upward through ancestry until roots are reached,
then assemble and write the {meta, nodes, edges} graph.
"""

import argparse
import datetime
import json
import os
import sys

from smgraph.graph import assemble_graph
from smgraph.rcsb import build_search_query, fetch_entries, search_entry_ids


def _pdb_parents(entry):
    return [sm["accession_code"].upper()
            for sm in (entry.get("starting_models") or [])
            if sm.get("source_name") == "PDB" and sm.get("accession_code")]


def walk_and_collect(seed_ids, fetch_fn, max_depth):
    """Fetch seeds, then follow starting-model references up to max_depth rounds.

    fetch_fn(ids) -> {id: normalized_entry}. Injected so tests avoid network.
    Returns every normalized entry gathered along the way.
    """
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

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(graph, f)
    m = graph["meta"]
    print(f"Wrote {a.out}: {m['node_count']} nodes, {m['edge_count']} edges, "
          f"max generation {m['max_generation']}", file=sys.stderr)


if __name__ == "__main__":
    main()
