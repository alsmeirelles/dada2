"""DADA's internal model adapter interface (spec 4.2).

It is distinct from the API-facing ``BaseModelAdapter``: these adapters train
the proxy and target models of one task family and measure the target model.
"""

from abc import ABC, abstractmethod
from pathlib import Path

from dada_api.active_learning.dada_al.dataset.pai_schema import PAIManifest


class ModelAdapter(ABC):
    """Training and evaluation of one task family's models."""

    @abstractmethod
    def train(
        self,
        model_name: str,
        training: PAIManifest,
        *,
        epochs: int,
        seed: int,
        output: Path,
        name: str,
    ) -> Path:
        """Train a model on the accepted training data.

        Args:
            model_name: Proxy or target model name.
            training: Training manifest.
            epochs: Training epochs.
            seed: Training seed.
            output: Folder receiving the run.
            name: Name of the run.

        Returns:
            The trained checkpoint.
        """

    @abstractmethod
    def evaluate(
        self, checkpoint: Path, manifest: PAIManifest, metric: str, output: Path
    ) -> dict[str, float]:
        """Measure a trained model on a held-out split.

        Args:
            checkpoint: Trained target model.
            manifest: Validation or test manifest.
            metric: The project's metric.
            output: Scratch folder.

        Returns:
            The metric and any companion metrics, each in ``[0, 1]``.
        """
