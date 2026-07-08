"""Assemble a single self-contained smgraph.html.

Inlines the vendored JS libraries and the base64-encoded dataset into the HTML
template so the result works offline with no external requests.
"""

import argparse
import base64


def build_html(template, data_json, libs):
    """Replace the four injection markers in ``template``.

    libs maps marker name -> library body, e.g. {"__CYTOSCAPE__": "<js>"}.
    ``data_json`` is the raw JSON text, embedded as base64 at ``__DATA_B64__``.
    """
    out = template
    for marker, body in libs.items():
        out = out.replace("/*" + marker + "*/", body)
    b64 = base64.b64encode(data_json.encode()).decode()
    out = out.replace("__DATA_B64__", b64)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build self-contained smgraph.html")
    ap.add_argument("--template", default="smgraph.template.html")
    ap.add_argument("--data", default="data/thrombin.json")
    ap.add_argument("--out", default="smgraph.html")
    a = ap.parse_args(argv)
    libs = {
        "__FORCEGRAPH__": open("vendor/force-graph.min.js").read(),
    }
    html = build_html(open(a.template).read(), open(a.data).read(), libs)
    with open(a.out, "w") as f:
        f.write(html)
    print(f"Wrote {a.out}: {len(html)} bytes")


if __name__ == "__main__":
    main()
