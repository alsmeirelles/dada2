"""Class-agnostic grouping of several raters' objects into candidate objects (D13)."""

import itertools
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TypeVar

import numpy as np
from scipy.optimize import linear_sum_assignment

from dada_api.consensus.numeric import quantize

T = TypeVar("T")


@dataclass(frozen=True, order=True)
class Member:
    """One object of one rater, ordered by rater and then by position.

    Attributes:
        rater: Index of the rater's object list.
        index: Index of the object inside that list.
    """

    rater: int
    index: int


@dataclass(frozen=True)
class Group:
    """A candidate object holding at most one object per rater.

    Attributes:
        members: The grouped objects, sorted by rater.
        ambiguous: Whether an equal-overlap alternative would have grouped
            these objects differently, so the grouping needs review.
    """

    members: tuple[Member, ...]
    ambiguous: bool


@dataclass(frozen=True)
class Grouping:
    """Every object of an image, grouped into candidates.

    Attributes:
        groups: One group per candidate, singletons included, ordered by their
            first member; every object that is not a duplicate is in exactly
            one group.
        duplicates: Same-rater duplicates, which take no part in any group.
    """

    groups: tuple[Group, ...]
    duplicates: tuple[Member, ...]


def group(
    objects: Sequence[Sequence[T]],
    overlap: Callable[[T, T], float],
    threshold: float,
    may_overlap: Callable[[T, T], bool] | None = None,
) -> Grouping:
    """Group objects that describe the same thing, never trusting their class.

    Overlaps are quantized before every comparison. An object at or above the
    threshold with an earlier object of the same rater is a duplicate. Each
    pair of raters is matched one-to-one by a maximum-weight assignment, and
    the kept matches become edges. Edges are merged from the highest overlap
    down under complete linkage: two groups join only when they share no rater
    and every cross pair meets the threshold, so one large object cannot
    bridge two nearby ones. Within one tier of equal overlap, an edge whose
    merge was possible before the tier but did not happen shows that the
    result depended on processing order; both of its groups, and anything
    they later merge with, are ambiguous.

    Args:
        objects: One list of objects per rater, in canonical order.
        overlap: Symmetric overlap measure between two objects.
        threshold: Inclusive minimum overlap for two objects to match.
        may_overlap: Optional cheap prefilter; when it returns False the pair
            is treated as having no overlap.

    Returns:
        The candidate groups and the duplicates.
    """
    limit = quantize(threshold)

    def score(first: T, second: T) -> Decimal:
        """Return the quantized overlap of two objects."""
        if may_overlap is not None and not may_overlap(first, second):
            return Decimal(0)
        return quantize(overlap(first, second))

    duplicates: list[Member] = []
    kept: list[list[Member]] = []
    for rater, items in enumerate(objects):
        survivors: list[Member] = []
        for index, item in enumerate(items):
            if any(score(items[earlier], item) >= limit for earlier in range(index)):
                duplicates.append(Member(rater, index))
            else:
                survivors.append(Member(rater, index))
        kept.append(survivors)

    scores: dict[tuple[Member, Member], Decimal] = {}
    edges: list[tuple[Decimal, Member, Member]] = []
    for left, right in itertools.combinations(kept, 2):
        if not left or not right:
            continue
        for a in left:
            for b in right:
                scores[a, b] = score(
                    objects[a.rater][a.index], objects[b.rater][b.index]
                )
        weights = np.array(
            [
                [float(scores[a, b]) if scores[a, b] >= limit else 0.0 for b in right]
                for a in left
            ]
        )
        rows, columns = linear_sum_assignment(weights, maximize=True)
        for row, column in zip(rows, columns, strict=True):
            a, b = left[row], right[column]
            if scores[a, b] >= limit:
                edges.append((scores[a, b], a, b))
    edges.sort(key=lambda edge: (-edge[0], edge[1], edge[2]))

    group_of = {
        member: position
        for position, member in enumerate(itertools.chain.from_iterable(kept))
    }
    members = {position: [member] for member, position in group_of.items()}
    ambiguous: set[int] = set()

    def joinable(first: int, second: int) -> bool:
        """Return whether two groups may merge under complete linkage."""
        if {m.rater for m in members[first]} & {m.rater for m in members[second]}:
            return False
        return all(
            scores[min(a, b), max(a, b)] >= limit
            for a in members[first]
            for b in members[second]
        )

    def merge(first: int, second: int) -> None:
        """Move every member of the second group into the first."""
        for member in members[second]:
            group_of[member] = first
        members[first].extend(members.pop(second))
        if second in ambiguous:
            ambiguous.discard(second)
            ambiguous.add(first)

    for _, tier in itertools.groupby(edges, key=lambda edge: edge[0]):
        possible = [(a, b) for _, a, b in tier if joinable(group_of[a], group_of[b])]
        for a, b in possible:
            if joinable(group_of[a], group_of[b]):
                merge(group_of[a], group_of[b])
        for a, b in possible:
            if group_of[a] != group_of[b]:
                ambiguous.update((group_of[a], group_of[b]))

    groups = sorted(
        (
            Group(tuple(sorted(grouped)), position in ambiguous)
            for position, grouped in members.items()
        ),
        key=lambda candidate: candidate.members[0],
    )
    return Grouping(tuple(groups), tuple(duplicates))
