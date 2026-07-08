"""Pure graph logic for starting-model provenance.

No I/O. Consumes normalized entry dicts (see smtree.rcsb.normalize_entry) and
produces the JSON graph described in the design doc section 7.
"""


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
