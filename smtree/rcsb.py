"""RCSB PDB Search + Data (GraphQL) client.

Standard library only. Network access is funneled through an injectable
``opener`` callable so the pure logic can be unit-tested without hitting the
network.
"""

import json
import time
import urllib.parse
import urllib.request

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
    """Build an RCSB Search API request body.

    Exactly one input is used; precedence query > uniprot > text. Always scopes
    to experimental entries and asks for all hits in one response.
    """
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
    """Map one GraphQL ``entries`` element to the shape assemble_graph wants."""
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
        time.sleep(0.2)  # politeness between batches
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
