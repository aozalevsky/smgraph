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
