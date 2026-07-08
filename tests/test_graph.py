from smtree.graph import compute_generations


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
