import uuid

from tuneforge.ingestion.chunking import build_tokenizer, chunk_into_source_records
from tuneforge.ingestion.documents import convert_document


def test_chunks_carry_heading_and_are_grounded_in_source_text(tmp_path):
    path = tmp_path / "policy.md"
    path.write_text(
        "# Company Policy\n\n"
        "## Vacation Policy\n\n"
        "Employees get 20 days of paid vacation per year.\n\n"
        "## Sick Leave\n\n"
        "Employees get 10 days of paid sick leave per year.\n"
    )
    document = convert_document(path)
    tokenizer = build_tokenizer("gpt2", max_tokens=64)
    document_id = uuid.uuid4()

    records = chunk_into_source_records(
        document,
        document_id=document_id,
        source_name=path.name,
        source_hash="deadbeef",
        tokenizer=tokenizer,
    )

    assert len(records) == 2
    assert records[0].heading == "Vacation Policy"
    assert "20 days" in records[0].text
    assert records[1].heading == "Sick Leave"
    assert "10 days" in records[1].text
    for record in records:
        assert record.document_id == document_id
        assert record.source_hash == "deadbeef"
        assert record.source_name == "policy.md"


def test_chunk_ids_are_unique_and_stable_within_a_document(tmp_path):
    path = tmp_path / "policy.md"
    path.write_text("# Title\n\nFirst paragraph.\n\nSecond paragraph.\n")
    document = convert_document(path)
    tokenizer = build_tokenizer("gpt2", max_tokens=64)
    document_id = uuid.uuid4()

    records = chunk_into_source_records(
        document, document_id=document_id, source_name="policy.md", source_hash="abc123", tokenizer=tokenizer
    )

    chunk_ids = [r.chunk_id for r in records]
    assert len(chunk_ids) == len(set(chunk_ids))
