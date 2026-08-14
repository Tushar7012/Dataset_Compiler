import uuid

from tuneforge.records import CPTRecord, RecordMetadata
from tuneforge.validation.deduplication import deduplicate


def _record(text: str) -> CPTRecord:
    return CPTRecord(text=text, metadata=RecordMetadata(document_id=uuid.uuid4(), source_name="doc.md", source_hash="deadbeef"))


def test_exact_duplicates_are_removed():
    records = [_record("Employees get 20 days of vacation."), _record("Employees get 20 days of vacation.")]
    result = deduplicate(records)
    assert len(result.kept) == 1
    assert result.exact_duplicates == 1


def test_exact_duplicate_detection_ignores_whitespace_and_case():
    records = [_record("Employees get 20 days of vacation."), _record("  employees   get 20 DAYS of vacation.  ")]
    result = deduplicate(records)
    assert len(result.kept) == 1
    assert result.exact_duplicates == 1


def test_near_duplicates_are_removed():
    records = [
        _record("The quick brown fox jumps over the lazy dog in the park today"),
        _record("The quick brown fox jumps over the lazy dog in the park yesterday"),
    ]
    result = deduplicate(records, near_duplicate_threshold=0.5)
    assert len(result.kept) == 1
    assert result.near_duplicates == 1


def test_distinct_content_is_all_kept():
    records = [
        _record("Employees get 20 days of paid vacation per year."),
        _record("The office is closed on all federal holidays."),
        _record("Remote work requests must be approved by a manager."),
    ]
    result = deduplicate(records)
    assert len(result.kept) == 3
    assert result.exact_duplicates == 0
    assert result.near_duplicates == 0
