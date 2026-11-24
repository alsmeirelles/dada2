"""Embedding hooks of DADA (spec 4.2).

Classification embeddings come from a forward hook on the ``timm`` global
pooling layer. Object embeddings come from a forward hook on the YOLO head,
which receives the three neck maps P3, P4, and P5: each object box is pooled
with a 1x1 ``RoIAlign`` on all three levels at once, and the concatenation is
L2-normalized.
"""

from contextlib import contextmanager
from typing import Any

import torch
from torchvision.ops import roi_align

EPSILON = 1e-12


def l2_normalize(vectors: torch.Tensor) -> torch.Tensor:
    """Project vectors onto the unit sphere along their last axis."""
    return vectors / (vectors.norm(dim=-1, keepdim=True) + EPSILON)


@contextmanager
def capture(module: torch.nn.Module):
    """Record a module's inputs and output while the block runs.

    Args:
        module: Module to observe.

    Yields:
        A dict that receives ``inputs`` and ``output`` at every forward.
    """
    seen: dict[str, Any] = {}

    def hook(_: torch.nn.Module, inputs: Any, output: Any) -> None:
        seen["inputs"] = inputs
        seen["output"] = output

    handle = module.register_forward_hook(hook)
    try:
        yield seen
    finally:
        handle.remove()


def pooled_features(model: torch.nn.Module, images: torch.Tensor) -> tuple:
    """Run a ``timm`` classifier and return its logits and pooled embeddings.

    Args:
        model: ``timm`` model with a ``global_pool`` layer.
        images: Normalized batch of shape ``(B, 3, H, W)``.

    Returns:
        Logits of shape ``(B, C)`` and L2-normalized embeddings ``(B, D)``.
    """
    with capture(model.global_pool) as seen:
        logits = model(images)
    return logits, l2_normalize(seen["output"].flatten(1))


def roi_features(
    feats: list[torch.Tensor], boxes: torch.Tensor, strides: torch.Tensor
) -> torch.Tensor:
    """Pool every box on the three neck levels and normalize the result.

    Args:
        feats: P3, P4, and P5 maps of one image, each ``(1, C, H, W)``.
        boxes: ``xyxy`` boxes in network-input pixels, shape ``(M, 4)``.
        strides: Stride of each level.

    Returns:
        Embeddings of shape ``(M, C3 + C4 + C5)``.
    """
    rois = torch.cat([boxes.new_zeros(len(boxes), 1), boxes], dim=1)
    pooled = [
        roi_align(
            level.float(),
            rois.float(),
            output_size=(1, 1),
            spatial_scale=1.0 / float(stride),
            aligned=True,
        ).flatten(1)
        for level, stride in zip(feats, strides, strict=True)
    ]
    return l2_normalize(torch.cat(pooled, dim=1))
