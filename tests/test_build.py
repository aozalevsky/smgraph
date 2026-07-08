import base64
import json

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
