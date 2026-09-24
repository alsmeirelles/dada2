"""Dataset layout preparation schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from dada_api.schemas.project import DatasetLayoutName


class DatasetLayoutResponse(BaseModel):
    """A project's prepared layout, its initial batches, and its training pool.

    Before preparation every count is zero and ``prepared_at`` is null. A
    ``single_batch`` project has no split rows, no first training batch, and
    no training pool.
    """

    dataset_layout: DatasetLayoutName
    prepared_at: datetime | None
    train_size: int
    validation_size: int
    test_size: int
    first_training_batch_size: int | None
    training_pool_size: int
    batch_ids: list[UUID]
    annotation_import_id: UUID | None
