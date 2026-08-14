from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class UnsupportedStructuredFormatError(RuntimeError):
    pass


class EmptyStructuredFileError(RuntimeError):
    pass


@dataclass(frozen=True)
class StructuredRow:
    row_id: str
    data: dict[str, Any]
    source_name: str
    source_hash: str


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_csv_rows(path: Path) -> list[StructuredRow]:
    source_hash = _hash_file(path)
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [
            StructuredRow(row_id=str(i), data=dict(row), source_name=path.name, source_hash=source_hash)
            for i, row in enumerate(reader)
        ]
    if not rows:
        raise EmptyStructuredFileError(f"{path.name}: no data rows")
    return rows


def load_json_rows(path: Path) -> list[StructuredRow]:
    source_hash = _hash_file(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        raise EmptyStructuredFileError(f"{path.name}: expected a non-empty JSON array or object")
    return [
        StructuredRow(row_id=str(i), data=row, source_name=path.name, source_hash=source_hash)
        for i, row in enumerate(data)
    ]


def load_jsonl_rows(path: Path) -> list[StructuredRow]:
    source_hash = _hash_file(path)
    rows = []
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            rows.append(
                StructuredRow(row_id=str(i), data=json.loads(line), source_name=path.name, source_hash=source_hash)
            )
    if not rows:
        raise EmptyStructuredFileError(f"{path.name}: no data rows")
    return rows


LOADERS = {
    ".csv": load_csv_rows,
    ".json": load_json_rows,
    ".jsonl": load_jsonl_rows,
}


def load_structured_rows(path: Path) -> list[StructuredRow]:
    loader = LOADERS.get(path.suffix.lower())
    if loader is None:
        raise UnsupportedStructuredFormatError(f"{path.name}: unsupported structured format {path.suffix!r}")
    return loader(path)
