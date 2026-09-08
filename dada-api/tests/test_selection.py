"""Reproducibility of the media selection used to build annotation batches."""

import pytest

from dada_api.services import selection

CANDIDATES = [f"media-{index:03d}" for index in range(200)]


def test_same_input_and_seed_reproduce_the_same_selection() -> None:
    first = selection.choose(CANDIDATES, 25, 4242)
    second = selection.choose(CANDIDATES, 25, 4242)

    assert first == second
    assert len(first) == 25
    assert len(set(first)) == 25
    assert set(first) <= set(CANDIDATES)


def test_a_different_seed_selects_differently() -> None:
    assert selection.choose(CANDIDATES, 25, 4242) != selection.choose(
        CANDIDATES, 25, 9999
    )


def test_a_different_input_order_is_a_different_selection_input() -> None:
    reversed_candidates = list(reversed(CANDIDATES))

    assert selection.fingerprint(CANDIDATES) != selection.fingerprint(
        reversed_candidates
    )
    assert selection.fingerprint(CANDIDATES) == selection.fingerprint(list(CANDIDATES))


def test_selecting_more_than_is_available_is_refused() -> None:
    with pytest.raises(ValueError):
        selection.choose(CANDIDATES, len(CANDIDATES) + 1, 1)


def test_seeds_are_generated_within_the_persisted_range() -> None:
    seeds = {selection.new_seed() for _ in range(50)}

    assert len(seeds) > 1
    assert all(0 <= seed < 2**selection.SEED_BITS for seed in seeds)
