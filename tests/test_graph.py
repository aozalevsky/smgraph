from smgraph.graph import assemble_graph, classify_origin, compute_generations


def test_classify_origin():
    assert classify_origin(True, None) == "derived"           # has a recorded parent
    assert classify_origin(True, "SAD") == "derived"
    assert classify_origin(False, "MOLECULAR REPLACEMENT") == "mr_unrecorded"
    assert classify_origin(False, "MR") == "mr_unrecorded"
    assert classify_origin(False, "MR-SAD") == "mr_unrecorded"  # MR wins over experimental
    assert classify_origin(False, "SAD") == "experimental"
    assert classify_origin(False, "MAD") == "experimental"
    assert classify_origin(False, "MIRAS") == "experimental"   # contains MIR
    assert classify_origin(False, None) == "unknown"           # absence != phased
    assert classify_origin(False, "") == "unknown"
    assert classify_origin(False, "FOURIER SYNTHESIS") == "unknown"
    assert classify_origin(False, "OTHER") == "unknown"


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


def _entry(title="t", sms=(), phasing=None):
    return {"title": title, "method": "X-RAY DIFFRACTION", "resolution": 2.0,
            "year": 2010, "organism": "Homo sapiens", "phasing_method": phasing,
            "starting_models": [{"accession_code": a, "source_name": "PDB",
                                 "type": "experimental model"} for a in sms]}


def test_assemble_sets_origin():
    entries = {
        "EXP": _entry(phasing="SAD"),                    # true experimental root
        "MRU": _entry(phasing="MOLECULAR REPLACEMENT"),  # MR but no recorded parent
        "UNK": _entry(phasing=None),                     # unknown provenance
        "CHILD": _entry(sms=["EXP"], phasing="MOLECULAR REPLACEMENT"),
    }
    g = assemble_graph(entries, seed_ids=set(entries), generated_utc="2026-07-08T00:00:00Z")
    o = {n["id"]: n["origin"] for n in g["nodes"]}
    assert o["EXP"] == "experimental"
    assert o["MRU"] == "mr_unrecorded"     # NOT treated as a phased root
    assert o["UNK"] == "unknown"
    assert o["CHILD"] == "derived"
    ph = {n["id"]: n["phasing_method"] for n in g["nodes"]}
    assert ph["MRU"] == "MOLECULAR REPLACEMENT"


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
