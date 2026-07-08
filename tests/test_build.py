import base64
import json

from build import build_html


def test_build_injects_data_and_libs():
    tmpl = 'X /*__FORCEGRAPH__*/ Y D="__DATA_B64__";'
    data = json.dumps({"meta": {}, "nodes": [], "edges": []})
    out = build_html(tmpl, data, {"__FORCEGRAPH__": "FG"})
    assert "FG" in out
    assert "__DATA_B64__" not in out and "/*__FORCEGRAPH__*/" not in out
    b64 = out.split('D="', 1)[1].split('"', 1)[0]
    assert json.loads(base64.b64decode(b64)) == {"meta": {}, "nodes": [],
                                                 "edges": []}
