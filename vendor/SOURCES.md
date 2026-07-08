# Vendored libraries

Downloaded 2026-07-08 for fully-offline, self-contained `smtree.html`.
Pinned versions, minified builds fetched from unpkg:

| File | Version | Source URL |
|------|---------|------------|
| `cytoscape.min.js` | 3.30.2 | https://unpkg.com/cytoscape@3.30.2/dist/cytoscape.min.js |
| `dagre.min.js` | 0.8.5 | https://unpkg.com/dagre@0.8.5/dist/dagre.min.js |
| `cytoscape-dagre.js` | 2.5.0 | https://unpkg.com/cytoscape-dagre@2.5.0/cytoscape-dagre.js |

## Load order (required)

`cytoscape-dagre` is a UMD build; in the browser it reads the `dagre` global and
exposes `cytoscapeDagre`. They must be loaded in this order, then registered:

```
cytoscape.min.js  ->  dagre.min.js  ->  cytoscape-dagre.js  ->  cytoscape.use(cytoscapeDagre)
```

The hierarchy layout uses the `dagre` layout (from cytoscape-dagre); the force
layout uses Cytoscape's built-in `cose` (no extra extension needed).
