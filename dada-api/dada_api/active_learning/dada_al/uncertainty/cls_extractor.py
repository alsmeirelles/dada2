"""Classification uncertainty and embeddings with a deep ensemble or
multi-view TTA (spec 4.3.1).

A deep ensemble runs every proxy on the image and concatenates their unit
embeddings scaled by ``1 / sqrt(N)``; multi-view TTA runs one proxy on the
geometric views and averages its embeddings. Either way the uncertainty is
BALD over the softmax passes blended with the predictive entropy.
"""

import uuid
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from dada_api.active_learning.dada_al.acquisition.feature_extractor import (
    l2_normalize,
    pooled_features,
)
from dada_api.active_learning.dada_al.config.schema import (
    CandidateItem,
    DADAAlConfig,
    UncertaintyMethod,
)
from dada_api.active_learning.dada_al.dataset.pai_schema import PAIImage
from dada_api.active_learning.dada_al.models.timm_adapter import (
    TimmClassificationAdapter,
    crop_views,
)
from dada_api.active_learning.dada_al.uncertainty import metrics


class ClassificationExtractor:
    """Scores whole images of a subpool with the trained proxies."""

    def __init__(self, adapter: TimmClassificationAdapter, config: DADAAlConfig):
        """Bind the extractor to a timm adapter and the run configuration."""
        self.adapter = adapter
        self.config = config

    def extract(
        self, checkpoints: list[Path], images: list[PAIImage], media_root: str
    ) -> list[CandidateItem]:
        """Return one candidate per image.

        Args:
            checkpoints: The ensemble's proxies, or the single TTA proxy.
            images: Subpool images.
            media_root: Media root of the request.

        Returns:
            The scored images.
        """
        ensemble = self.config.uncertainty_method is UncertaintyMethod.DEEP_ENSEMBLE
        models = [self.adapter.load(path) for path in checkpoints]
        views = 1 if ensemble else self.config.cls_tta_views
        candidates = []
        with torch.no_grad():
            for image in images:
                with Image.open(Path(media_root) / image.file_name) as opened:
                    source = opened.convert("RGB")
                probabilities, embeddings = [], []
                for model in models:
                    batch = torch.stack(
                        [
                            self.adapter.tensor(model, view)
                            for view in crop_views(source, views)
                        ]
                    )
                    logits, features = pooled_features(model, batch)
                    probabilities.append(logits.softmax(1))
                    embeddings.append(features)
                passes = torch.cat(probabilities).cpu().numpy()
                if ensemble:
                    joined = torch.cat([item[0] for item in embeddings]) / np.sqrt(
                        len(models)
                    )
                else:
                    joined = embeddings[0].sum(0)
                feature = l2_normalize(joined).cpu().numpy()
                uncertainty = metrics.classification_uncertainty(
                    passes, self.config.cls_entropy_blend
                )
                candidates.append(
                    CandidateItem(
                        candidate_id=str(uuid.uuid5(uuid.NAMESPACE_URL, image.id)),
                        image_id=image.id,
                        bbox_xyxy=None,
                        segmentation=None,
                        pred_class_probs=passes.mean(0),
                        cls_uncertainty=uncertainty,
                        spatial_uncertainty=0.0,
                        total_uncertainty=uncertainty,
                        feature_vector=feature,
                    )
                )
        return candidates
