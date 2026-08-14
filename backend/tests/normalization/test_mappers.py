import uuid

import pytest

from tuneforge.ingestion.structured import StructuredRow
from tuneforge.normalization.detector import DetectedSchema
from tuneforge.normalization.mappers import InvalidRecordError, normalize_rows


def _row(data: dict, row_id: str = "0") -> StructuredRow:
    return StructuredRow(row_id=row_id, data=data, source_name="data.jsonl", source_hash="deadbeef")


def test_normalizes_text_row_to_cpt_record():
    [record] = normalize_rows([_row({"text": "hello"})], DetectedSchema.TEXT, document_id=uuid.uuid4())
    assert record.text == "hello"
    assert record.metadata.row_id == "0"
    assert record.metadata.source_hash == "deadbeef"


def test_normalizes_prompt_completion_row():
    [record] = normalize_rows(
        [_row({"prompt": "hi", "completion": "hello"})], DetectedSchema.PROMPT_COMPLETION, document_id=uuid.uuid4()
    )
    assert record.prompt == "hi"
    assert record.completion == "hello"


def test_normalizes_instruction_row_combining_instruction_and_input():
    [record] = normalize_rows(
        [_row({"instruction": "Summarize:", "input": "long text", "output": "short"})],
        DetectedSchema.INSTRUCTION_INPUT_OUTPUT,
        document_id=uuid.uuid4(),
    )
    assert record.prompt == "Summarize:\n\nlong text"
    assert record.completion == "short"


def test_normalizes_instruction_row_without_input():
    [record] = normalize_rows(
        [_row({"instruction": "Say hi", "output": "hi"})],
        DetectedSchema.INSTRUCTION_INPUT_OUTPUT,
        document_id=uuid.uuid4(),
    )
    assert record.prompt == "Say hi"


def test_normalizes_messages_row():
    [record] = normalize_rows(
        [_row({"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]})],
        DetectedSchema.MESSAGES,
        document_id=uuid.uuid4(),
    )
    assert [m.role for m in record.messages] == ["user", "assistant"]


def test_messages_row_rejects_consecutive_same_role():
    rows = [_row({"messages": [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]})]
    with pytest.raises(InvalidRecordError):
        normalize_rows(rows, DetectedSchema.MESSAGES, document_id=uuid.uuid4())


def test_messages_row_rejects_starting_with_assistant():
    rows = [_row({"messages": [{"role": "assistant", "content": "a"}]})]
    with pytest.raises(InvalidRecordError):
        normalize_rows(rows, DetectedSchema.MESSAGES, document_id=uuid.uuid4())


def test_messages_row_allows_leading_system_message():
    [record] = normalize_rows(
        [
            _row(
                {
                    "messages": [
                        {"role": "system", "content": "be nice"},
                        {"role": "user", "content": "hi"},
                        {"role": "assistant", "content": "hello"},
                    ]
                }
            )
        ],
        DetectedSchema.MESSAGES,
        document_id=uuid.uuid4(),
    )
    assert [m.role for m in record.messages] == ["system", "user", "assistant"]


def test_normalizes_conversations_row_remapping_roles():
    [record] = normalize_rows(
        [_row({"conversations": [{"from": "human", "value": "hi"}, {"from": "gpt", "value": "hello"}]})],
        DetectedSchema.CONVERSATIONS,
        document_id=uuid.uuid4(),
    )
    assert [m.role for m in record.messages] == ["user", "assistant"]
    assert record.messages[1].content == "hello"


def test_conversations_row_rejects_unknown_sender():
    rows = [_row({"conversations": [{"from": "alien", "value": "hi"}]})]
    with pytest.raises(InvalidRecordError):
        normalize_rows(rows, DetectedSchema.CONVERSATIONS, document_id=uuid.uuid4())


def test_normalizes_dpo_row():
    [record] = normalize_rows(
        [_row({"prompt": "q", "chosen": "good answer", "rejected": "bad answer"})],
        DetectedSchema.PROMPT_CHOSEN_REJECTED,
        document_id=uuid.uuid4(),
    )
    assert record.prompt[0].content == "q"
    assert record.chosen[0].content == "good answer"
    assert record.rejected[0].content == "bad answer"


def test_missing_required_field_raises_invalid_record_error():
    rows = [_row({"prompt": "hi"})]
    with pytest.raises(InvalidRecordError):
        normalize_rows(rows, DetectedSchema.PROMPT_COMPLETION, document_id=uuid.uuid4())


def test_preserves_original_row_id_and_source_metadata():
    [record] = normalize_rows(
        [_row({"text": "hello"}, row_id="42")], DetectedSchema.TEXT, document_id=uuid.uuid4()
    )
    assert record.metadata.row_id == "42"
    assert record.metadata.source_name == "data.jsonl"
