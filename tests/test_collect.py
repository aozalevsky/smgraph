from collect import walk_and_collect


def test_walk_follows_ancestry():
    universe = {
        "C": {"starting_models": [{"accession_code": "B", "source_name": "PDB"}]},
        "B": {"starting_models": [{"accession_code": "A", "source_name": "PDB"}]},
        "A": {"starting_models": []},
    }
    calls = []

    def fake_fetch(ids):
        calls.append(list(ids))
        return {i: universe[i] for i in ids if i in universe}

    got = walk_and_collect(["C"], fake_fetch, max_depth=5)
    assert set(got) == {"A", "B", "C"}          # walked all the way to root
    assert calls[0] == ["C"]                     # seeds first
    assert any("A" in c for c in calls[1:])      # A discovered via the walk


def test_walk_respects_max_depth():
    universe = {
        "C": {"starting_models": [{"accession_code": "B", "source_name": "PDB"}]},
        "B": {"starting_models": [{"accession_code": "A", "source_name": "PDB"}]},
        "A": {"starting_models": []},
    }

    def fake_fetch(ids):
        return {i: universe[i] for i in ids if i in universe}

    got = walk_and_collect(["C"], fake_fetch, max_depth=0)
    assert set(got) == {"C"}                     # no ancestry rounds
