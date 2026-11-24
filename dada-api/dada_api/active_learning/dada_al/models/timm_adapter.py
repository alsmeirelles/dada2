"""``timm`` image-classification adapter, EfficientNet-B1 proxy and B5 target
by default (spec 4.2.1).

Proxy and target see the same input size, the target model's own unless the
project sets one. Training starts from the pretrained weights, uses only the
images with exactly one accepted class (D10), and flips images horizontally
as its sole augmentation. An ensemble's proxies train side by side, each with
its own seed and batch order, and one after another when they do not fit in
memory together.
"""

from pathlib import Path
from typing import Any

import numpy as np
import timm
import torch
import torch.nn.functional as functional
from PIL import Image

from dada_api.active_learning.dada_al.dataset import pai_schema
from dada_api.active_learning.dada_al.models.base_adapter import ModelAdapter

LEARNING_RATE = 1e-4
WEIGHT_DECAY = 1e-4
VIEW_CROP = 0.90


def crop_views(image: Image.Image, count: int) -> list[Image.Image]:
    """Return the first ``count`` deterministic views of spec 4.3.1.

    The views are the identity, the horizontal flip, and 0.90 crops at the
    centre, the upper left, and the lower right.

    Args:
        image: Canonical image.
        count: Number of views, at most five.

    Returns:
        The views, still at their own sizes.
    """
    width, height = image.size
    crop_w, crop_h = round(width * VIEW_CROP), round(height * VIEW_CROP)
    left, top = (width - crop_w) // 2, (height - crop_h) // 2
    views = [
        image,
        image.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
        image.crop((left, top, left + crop_w, top + crop_h)),
        image.crop((0, 0, crop_w, crop_h)),
        image.crop((width - crop_w, height - crop_h, width, height)),
    ]
    return views[:count]


class TimmClassificationAdapter(ModelAdapter):
    """Trains, runs, and measures ``timm`` classifiers of one project."""

    def __init__(
        self,
        media_root: str,
        classes: int,
        target_model_name: str,
        *,
        image_size: int | None,
        batch_size: int,
        device: str,
    ) -> None:
        """Configure the adapter.

        Args:
            media_root: Media root of the request.
            classes: Number of project classes.
            target_model_name: Target model, whose input size is shared.
            image_size: Input size; the target's own when None.
            batch_size: Training batch size.
            device: Torch device.
        """
        self.media_root = media_root
        self.classes = classes
        self.size = (
            image_size or timm.get_pretrained_cfg(target_model_name).input_size[-1]
        )
        self.batch_size = batch_size
        self.device = device

    def build(self, model_name: str, pretrained: bool = True) -> torch.nn.Module:
        """Create a classifier with the project's number of classes."""
        return timm.create_model(
            model_name, pretrained=pretrained, num_classes=self.classes
        ).to(self.device)

    def tensor(self, model: torch.nn.Module, image: Image.Image) -> torch.Tensor:
        """Resize and normalize one image for a model."""
        config = timm.data.resolve_model_data_config(model)
        array = np.asarray(
            image.convert("RGB").resize((self.size, self.size)), np.float32
        )
        values = torch.from_numpy(array / 255.0).permute(2, 0, 1)
        mean = torch.tensor(config["mean"]).view(3, 1, 1)
        std = torch.tensor(config["std"]).view(3, 1, 1)
        return ((values - mean) / std).to(self.device)

    def _items(
        self, manifest: pai_schema.PAIManifest, output: Path
    ) -> list[tuple[Path, int]]:
        """Return the single-class images of a manifest."""
        items, _ = pai_schema.classification_items(
            manifest, self.media_root, output / "images"
        )
        return items

    def _batches(self, items: list[tuple[Path, int]], seed: int):
        """Yield shuffled ``(paths, labels)`` batches for one epoch."""
        generator = torch.Generator().manual_seed(seed)
        order = torch.randperm(len(items), generator=generator).tolist()
        for start in range(0, len(order), self.batch_size):
            chosen = [items[index] for index in order[start : start + self.batch_size]]
            yield chosen, torch.Generator().manual_seed(seed + start)

    def _step(
        self,
        model: torch.nn.Module,
        optimizer: torch.optim.Optimizer,
        chosen: list[tuple[Path, int]],
        generator: torch.Generator,
    ) -> None:
        """Take one optimization step on a batch, flipping images at random."""
        images = []
        for path, _ in chosen:
            with Image.open(path) as opened:
                image = opened.convert("RGB")
            if torch.rand(1, generator=generator).item() < 0.5:
                image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            images.append(self.tensor(model, image))
        labels = torch.tensor([label for _, label in chosen], device=self.device)
        optimizer.zero_grad()
        functional.cross_entropy(model(torch.stack(images)), labels).backward()
        optimizer.step()

    def train_many(
        self,
        model_name: str,
        training: pai_schema.PAIManifest,
        *,
        seeds: list[int],
        epochs: int,
        output: Path,
        name: str,
    ) -> list[Path]:
        """Train one model per seed, side by side when memory allows.

        Args:
            model_name: Model to train.
            training: Training manifest.
            seeds: One seed per model, for its initialization and batch order.
            epochs: Training epochs.
            output: Folder receiving the checkpoints.
            name: Prefix of the checkpoint files.

        Returns:
            One checkpoint per seed.
        """
        items = self._items(training, output)
        try:
            return self._train(model_name, items, seeds, epochs, output, name)
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            return [
                self._train(
                    model_name, items, [seed], epochs, output, f"{name}-{seed}"
                )[0]
                for seed in seeds
            ]

    def _train(
        self,
        model_name: str,
        items: list[tuple[Path, int]],
        seeds: list[int],
        epochs: int,
        output: Path,
        name: str,
    ) -> list[Path]:
        """Train models in lockstep, each on its own batch order."""
        models, optimizers = [], []
        for seed in seeds:
            torch.manual_seed(seed)
            model = self.build(model_name)
            model.train()
            models.append(model)
            optimizers.append(
                torch.optim.AdamW(
                    model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY
                )
            )
        for epoch in range(epochs):
            streams = [self._batches(items, seed * 1000 + epoch) for seed in seeds]
            for batches in zip(*streams, strict=True):
                for model, optimizer, (chosen, generator) in zip(
                    models, optimizers, batches, strict=True
                ):
                    self._step(model, optimizer, chosen, generator)
        output.mkdir(parents=True, exist_ok=True)
        paths = []
        for seed, model in zip(seeds, models, strict=True):
            path = output / f"{name}-{seed}.pt"
            torch.save(
                {"model_name": model_name, "state_dict": model.state_dict()}, path
            )
            paths.append(path)
        return paths

    def train(
        self,
        model_name: str,
        training: pai_schema.PAIManifest,
        *,
        epochs: int,
        seed: int,
        output: Path,
        name: str,
    ) -> Path:
        """Train one model (spec 4.2.1)."""
        return self.train_many(
            model_name, training, seeds=[seed], epochs=epochs, output=output, name=name
        )[0]

    def load(self, checkpoint: Path) -> torch.nn.Module:
        """Load a trained classifier in evaluation mode."""
        stored: dict[str, Any] = torch.load(checkpoint, map_location=self.device)
        model = self.build(stored["model_name"], pretrained=False)
        model.load_state_dict(stored["state_dict"])
        return model.eval()

    def evaluate(
        self,
        checkpoint: Path,
        manifest: pai_schema.PAIManifest,
        metric: str,
        output: Path,
    ) -> dict[str, float]:
        """Measure accuracy and macro F1 over the classes (D9).

        Only images with exactly one accepted class are measured (D10).
        """
        model = self.load(checkpoint)
        items = self._items(manifest, output)
        truth, predicted = [], []
        with torch.no_grad():
            for path, label in items:
                with Image.open(path) as opened:
                    logits = model(self.tensor(model, opened)[None])
                truth.append(label)
                predicted.append(int(logits.argmax(1)))
        truth_array, predicted_array = np.array(truth), np.array(predicted)
        accuracy = float((truth_array == predicted_array).mean()) if items else 0.0
        scores = []
        for label in range(self.classes):
            hits = int(((truth_array == label) & (predicted_array == label)).sum())
            claimed = int((predicted_array == label).sum())
            actual = int((truth_array == label).sum())
            if claimed + actual:
                scores.append(2 * hits / (claimed + actual))
        return {"accuracy": accuracy, "f1": float(np.mean(scores)) if scores else 0.0}
