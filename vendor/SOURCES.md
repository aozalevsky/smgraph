# Vendored libraries

Downloaded for a fully-offline, self-contained `smtree.html`.

| File | Version | Source URL | Date |
|------|---------|------------|------|
| `force-graph.min.js` | 1.49.5 | https://unpkg.com/force-graph@1.49.5/dist/force-graph.min.js | 2026-07-08 |

`force-graph` (by Vasco Asturiano) is a self-contained UMD bundle that exposes
the global `ForceGraph`. It runs a live d3-force simulation on an HTML canvas:
dragging a node stretches its links and the graph springs back. Its `dagMode`
gives a layered (hierarchical) layout that is also a live, draggable simulation.
The bundle includes d3-force / d3-zoom / d3-drag — no other libraries are needed.

## History

- 2026-07-08: replaced Cytoscape.js + dagre + cytoscape-dagre with force-graph,
  to get a live spring simulation (edges deform on drag) and a lighter bundle.
