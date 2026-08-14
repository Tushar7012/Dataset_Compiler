from __future__ import annotations

import uuid

from tuneforge.ingestion.structured import StructuredRow
from tuneforge.normalization.detector import DetectedSchema
from tuneforge.normalization.mappers import normalize_rows


class ColumnMappingError(RuntimeError):
    pass


def apply_column_mapping(rows: list[StructuredRow], mapping: dict[str, str]) -> list[StructuredRow]:
    """`mapping` is {actual_column_name: canonical_field_name} — for when
    `detect_schema` came back inconclusive and a human says "column X is
    really the prompt" instead of a model guessing it.
    """
    remapped = []
    for row in rows:
        missing = [actual for actual in mapping if actual not in row.data]
        if missing:
            raise ColumnMappingError(f"row {row.row_id}: missing expected column(s) {missing}")
        new_data = dict(row.data)
        for actual, canonical in mapping.items():
            new_data[canonical] = new_data.pop(actual)
        remapped.append(
            StructuredRow(row_id=row.row_id, data=new_data, source_name=row.source_name, source_hash=row.source_hash)
        )
    return remapped


def preview_normalization(
    rows: list[StructuredRow],
    schema: DetectedSchema,
    *,
    document_id: uuid.UUID,
    limit: int = 20,
) -> list:
    return normalize_rows(rows[:limit], schema, document_id=document_id)
