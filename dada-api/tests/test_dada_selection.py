"""DADA parts that run on the CPU: uncertainty bounds, quota conservation,
the P7-09 edge cases, the gatekeeper, subpooling, and configuration."""

import json

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from pydantic import ValidationError  # noqa: E402

from dada_api.active_learning.dada_al.acquisition import dada_selector  # noqa: E402
from dada_api.active_learning.dada_al.acquisition.subpool_manager import (  # noqa: E402
    SubpoolManager,
)
from dada_api.active_learning.dada_al.config.schema import (  # noqa: E402
    CandidateItem,
    DADAAlConfig,
    DADASettings,
)
from dada_api.active_learning.dada_al.dataset.pai_schema import snap  # noqa: E402
from dada_api.active_learning.dada_al.uncertainty import metrics  # noqa: E402

RNG = np.random.default_rng(7)


def _config(task: str = "detection", budget: int = 4, **settings) -> DADAAlConfig:
    """Return a run configuration."""
    return DADAAlConfig.for_request(settings, task, budget)


def _candidate(
    name: str,
    uncertainty: float,
    image: str = "img",
    box: tuple | None = (0.0, 0.0, 10.0, 10.0),
) -> CandidateItem:
    """Return a candidate with a random unit feature."""
    feature = RNG.normal(size=8)
    return CandidateItem(
        candidate_id=name,
        image_id=image,
        bbox_xyxy=box,
        segmentation=None,
        pred_class_probs=np.array([0.5, 0.5]),
        cls_uncertainty=uncertainty,
        spatial_uncertainty=0.0,
        total_uncertainty=uncertainty,
        feature_vector=feature / np.linalg.norm(feature),
    )


def _unit(value: float) -> bool:
    """Return whether a measure lies in [0, 1]."""
    return 0.0 <= value <= 1.0


def test_classification_uncertainty_is_bounded_and_positive_on_a_boundary() -> None:
    unanimous = np.array([[0.5, 0.5]] * 3)
    split = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]])
    certain = np.array([[1.0, 0.0]] * 3)

    assert metrics.bald(unanimous) == pytest.approx(0.0)
    assert metrics.classification_uncertainty(unanimous, 0.2) == pytest.approx(0.2)
    assert metrics.classification_uncertainty(certain, 0.2) == pytest.approx(
        0.0, abs=1e-9
    )
    for passes in (split, *(RNG.dirichlet(np.ones(4), size=5) for _ in range(50))):
        assert _unit(metrics.classification_uncertainty(passes, 0.2))
        assert _unit(metrics.bald(passes))


def test_object_uncertainties_stay_bounded_in_every_edge_case() -> None:
    for _ in range(50):
        count = int(RNG.integers(1, 6))
        scores = RNG.random((count, 3))
        simplex = metrics.augmented_simplex(scores)
        weights = scores.max(1) / scores.max(1).sum()
        ious = RNG.uniform(0.5, 1.0, count)
        cls = metrics.cluster_class_uncertainty(simplex, 2.0)
        loc = metrics.cluster_localization_uncertainty(ious, weights, 0.5, 2.0, 0.3)
        dual = metrics.jensen_shannon(simplex.mean(0), metrics.background_simplex(3))
        coefficients = metrics.coefficient_dispersion(
            RNG.normal(size=(count, 32)), weights
        )
        mask = metrics.mask_uncertainty(
            metrics.boundary_band_entropy(RNG.random((20, 20)), 3), coefficients
        )
        assert np.allclose(simplex.sum(1), 1.0)
        for value in (cls, loc, dual, coefficients, mask):
            assert _unit(value)
        assert _unit(metrics.total_uncertainty(cls, loc, mask, 0.4, 0.3, 0.3))
        assert _unit(metrics.total_uncertainty(cls, loc, None, 0.5, 0.5, None))


def test_a_lone_proposal_falls_back_to_its_own_measures() -> None:
    simplex = metrics.augmented_simplex(np.array([[0.9, 0.1]]))

    assert metrics.shrinkage(1, 2.0) == 0.0
    assert metrics.cluster_class_uncertainty(simplex, 2.0) == pytest.approx(
        float(metrics.normalized_entropy(simplex[0]))
    )
    assert metrics.cluster_localization_uncertainty(
        np.array([1.0]), np.array([1.0]), 0.5, 2.0, 0.37
    ) == pytest.approx(0.37)


def test_a_one_to_one_miss_counts_as_disagreement() -> None:
    confident = metrics.augmented_simplex(np.array([[0.95, 0.01]]))[0]

    assert metrics.jensen_shannon(confident, confident) == pytest.approx(0.0)
    assert metrics.jensen_shannon(confident, metrics.background_simplex(2)) > 0.3


def test_dfl_entropy_and_dispersions_cover_their_extremes() -> None:
    sharp = np.full((4, 16), -50.0)
    sharp[:, 3] = 50.0
    flat = np.zeros((4, 16))
    box = np.array([0.0, 0.0, 10.0, 10.0])

    assert metrics.dfl_entropy(sharp) == pytest.approx(0.0, abs=1e-6)
    assert metrics.dfl_entropy(flat) == pytest.approx(1.0)
    assert metrics.pairwise_iou_dispersion([box, box, box]) == pytest.approx(0.0)
    assert metrics.pairwise_iou_dispersion([box, None, None]) == pytest.approx(1.0)
    assert metrics.boundary_band_entropy(np.zeros((10, 10)), 3) == 1.0


def test_quotas_conserve_the_budget_and_respect_capacity() -> None:
    assert dada_selector.allocate_quotas([10, 10, 10], [0.6, 0.3, 0.1], 10) == [6, 3, 1]
    assert dada_selector.allocate_quotas([1, 10, 10], [0.9, 0.05, 0.05], 10) == [
        1,
        5,
        4,
    ]
    assert dada_selector.allocate_quotas([5, 5], [0.0, 0.0], 4) == [2, 2]
    assert dada_selector.allocate_quotas([1, 1, 1], [0.2, 0.2, 0.2], 2) == [1, 1, 0]
    assert dada_selector.allocate_quotas([0, 3, 1], [0.0, 0.4, 0.9], 10) == [0, 3, 1]
    for _ in range(200):
        sizes = [int(size) for size in RNG.integers(0, 6, int(RNG.integers(1, 8)))]
        weights = [float(weight) for weight in RNG.random(len(sizes))]
        budget = int(RNG.integers(1, 20))
        quotas = dada_selector.allocate_quotas(sizes, weights, budget)
        assert sum(quotas) == min(budget, sum(sizes))
        assert all(
            0 <= quota <= size for quota, size in zip(quotas, sizes, strict=True)
        )


def test_selection_fills_each_cluster_with_its_most_uncertain_candidates() -> None:
    candidates = [
        _candidate("a", 0.9),
        _candidate("b", 0.8),
        _candidate("c", 0.1),
        _candidate("d", 0.2),
        _candidate("e", 0.0),
        _candidate("f", 0.0),
    ]
    labels = np.array([0, 0, 1, 1, 2, 2])

    chosen, reason = dada_selector.select(candidates, _config(budget=3), 1, labels)

    assert reason is None
    assert [item.candidate_id for item in chosen] == ["a", "b", "d"]


def test_ties_and_zero_uncertainty_are_resolved_by_identifier() -> None:
    candidates = [_candidate(name, 0.0) for name in ("z", "y", "x", "w")]
    labels = np.array([0, 0, 1, 1])

    chosen, _ = dada_selector.select(candidates, _config(budget=2), 1, labels)

    assert [item.candidate_id for item in chosen] == ["w", "y"]


def test_too_few_or_no_candidates_are_reported() -> None:
    few = [_candidate("a", 0.2), _candidate("b", 0.7)]

    chosen, reason = dada_selector.select(few, _config(budget=5), 1)
    empty, nothing = dada_selector.select([], _config(budget=5), 1)

    assert [item.candidate_id for item in chosen] == ["b", "a"]
    assert reason == "insufficient_candidates"
    assert empty == []
    assert nothing == "no_candidates"


def test_clustering_is_reproducible_and_capped_by_the_candidates() -> None:
    pytest.importorskip("sklearn")
    candidates = [_candidate(f"c{index:02d}", index / 30) for index in range(30)]
    config = _config(budget=7, num_clusters=50, pca_components=4)

    first, _ = dada_selector.select(candidates, config, 99)
    second, _ = dada_selector.select(candidates, config, 99)

    assert len(first) == 7
    assert [item.candidate_id for item in first] == [
        item.candidate_id for item in second
    ]


def test_the_gatekeeper_drops_known_objects_and_caps_candidates(tmp_path) -> None:
    pool = {
        "images": [
            {
                "id": "img",
                "annotation_status": "PARTIALLY_LABELED",
                "queried_rois": [
                    {"roi_id": "r1", "bbox_xyxy": [100.0, 100.0, 200.0, 200.0]},
                ],
            }
        ],
        "annotations": [{"image_id": "img", "bbox": [300.0, 300.0, 100.0, 100.0]}],
    }
    candidates = [
        _candidate("negative", 0.9, box=(105.0, 105.0, 205.0, 205.0)),
        _candidate("confirmed", 0.9, box=(300.0, 300.0, 395.0, 400.0)),
        _candidate("new", 0.5, box=(150.0, 150.0, 260.0, 260.0)),
        _candidate("other", 0.4, image="other", box=(100.0, 100.0, 200.0, 200.0)),
        _candidate("calm", 0.1, image="other", box=(0.0, 0.0, 5.0, 5.0)),
    ]
    manager = SubpoolManager(str(tmp_path), _config(max_object_candidates=2))

    kept = manager.gatekeeper(candidates, pool)

    assert [item.candidate_id for item in kept] == ["new", "other"]


def test_the_subpool_is_reused_then_renewed(tmp_path) -> None:
    images = [
        {"id": f"i{index}", "annotation_status": "UNLABELED"} for index in range(10)
    ] + [{"id": "done", "annotation_status": "EXHAUSTIVELY_LABELED"}]
    manager = SubpoolManager(
        str(tmp_path), _config(image_subpool_size=4, subpool_renewal_interval=2)
    )

    first = manager.image_subpool(images, 3, 11)
    retried = manager.image_subpool(images, 3, 11)
    reused = manager.image_subpool(images, 4, 12)
    renewed = manager.image_subpool(images, 5, 13)

    assert len(first) == 4
    assert all(image["id"] != "done" for image in first)
    assert retried == first == reused
    assert json.loads((tmp_path / "subpool.json").read_text())["iteration"] == 5
    assert len(renewed) == 4


def test_settings_resolve_task_defaults_and_refuse_mismatches() -> None:
    detection = DADASettings.model_validate({}, context={"task": "detection"})
    segmentation = DADASettings.model_validate({}, context={"task": "segmentation"})
    classification = DADASettings.model_validate({}, context={"task": "classification"})

    assert (detection.proxy_model_name, detection.target_model_name) == (
        "yolo26n.pt",
        "yolo26x.pt",
    )
    assert (detection.cls_weight, detection.loc_weight, detection.mask_weight) == (
        0.5,
        0.5,
        None,
    )
    assert (segmentation.cls_weight, segmentation.mask_weight) == (0.4, 0.3)
    assert classification.uncertainty_method == "deep_ensemble"
    assert classification.target_model_name == "efficientnet_b5"
    for task, settings in (
        ("classification", {"uncertainty_method": "pre_nms"}),
        ("detection", {"uncertainty_method": "deep_ensemble"}),
        ("detection", {"target_model_name": "yolo26x-seg.pt"}),
        ("segmentation", {"proxy_model_name": "yolo26n.pt"}),
        ("detection", {"target_model_name": "yolov8x.pt"}),
        ("classification", {"target_model_name": "yolo11x.pt"}),
        ("detection", {"cls_weight": 0.7}),
        ("detection", {"mask_weight": 0.2}),
        ("segmentation", {"cls_weight": 0.5}),
    ):
        with pytest.raises(ValidationError):
            DADASettings.model_validate(settings, context={"task": task})
    assert DADASettings.model_validate(
        {"proxy_model_name": "yolo26n.pt", "target_model_name": "yolo12x.pt"},
        context={"task": "detection"},
    )


def test_regions_are_padded_inside_the_image_on_an_exact_grid() -> None:
    assert dada_selector.queried_roi((10.0, 20.0, 110.0, 70.0), 0.15, 100, 80) == [
        0.0,
        12.5,
        100.0,
        77.5,
    ]
    x = snap(0.123456, 0, 640, -1)
    end = snap(639.999999, 0, 640, 1)
    assert x + (end - x) == end <= 640
