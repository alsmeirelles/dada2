"""Project quality measures: formulas, metric choice, and suppression (D20)."""

from dada_api.services.quality import ItemQuality, agreement, report


def _items(resolved: int, reviewed: int = 0, **others: int) -> list[ItemQuality]:
    """Return resolved items, the first ``reviewed`` of them reviewed, plus
    items in other states."""
    items = [
        ItemQuality("resolved", index < reviewed, [("box_iou", 0.5 + index / 100)])
        for index in range(resolved)
    ]
    for status, count in others.items():
        items.extend(
            ItemQuality(status, False, [("box_iou", 0.1)]) for _ in range(count)
        )
    return items


def test_every_value_is_hidden_below_thirty_resolved_items() -> None:
    result = report("detection", _items(29, reviewed=3, pending=10))

    assert result["suppressed"] is True
    assert result["resolved_items"] == 29
    assert result["total_items"] == 39
    assert result["review_rate"] is None
    assert result["resolution_rate"] is None
    assert result["agreement"] == [
        {"metric": "box_iou", "observations": 29, "median": None}
    ]


def test_rates_count_resolved_items_and_ignore_cancelled_ones() -> None:
    result = report(
        "detection", _items(30, reviewed=6, pending=8, in_review=2, cancelled=5)
    )

    assert result["suppressed"] is False
    assert result["total_items"] == 40
    assert result["review_rate"] == 0.2
    assert result["resolution_rate"] == 0.75
    assert result["agreement"] == [
        {"metric": "box_iou", "observations": 30, "median": 0.645}
    ]


def test_an_agreement_backed_by_fewer_than_five_candidates_is_hidden() -> None:
    items = [ItemQuality("resolved", False, []) for _ in range(30)]
    items[0] = ItemQuality("resolved", False, [("mask_dice", 0.9)] * 4)
    items[1] = ItemQuality("resolved", False, [("mask_iou", 0.7)] * 5)

    result = report("segmentation", items)

    assert result["agreement"] == [
        {"metric": "mask_dice", "observations": 4, "median": None},
        {"metric": "mask_iou", "observations": 5, "median": 0.7},
    ]


def test_each_task_reads_its_own_consensus_metric() -> None:
    classification = [
        {"metrics": {"support": {"numerator": 2, "denominator": 3}}},
        {"metrics": {"support": {"numerator": 0, "denominator": 0}}},
    ]
    detection = [
        {"metrics": {"support": {"numerator": 2, "denominator": 2}, "median_iou": 0.8}},
        {"metrics": {"median_iou": None}},
    ]
    segmentation = [
        {"metrics": {"median_overlap": 0.6, "matching_metric": "dice"}},
        {"metrics": {"median_overlap": 0.5, "matching_metric": "iou"}},
    ]

    assert agreement("classification", classification) == [("winner_support", 2 / 3)]
    assert agreement("detection", detection) == [("box_iou", 0.8)]
    assert agreement("segmentation", segmentation) == [
        ("mask_dice", 0.6),
        ("mask_iou", 0.5),
    ]
