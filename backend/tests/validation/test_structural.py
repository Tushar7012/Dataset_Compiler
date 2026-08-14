import uuid

import pytest

from tuneforge.records import ChatMessage, CPTRecord, DPORecord, RecordMetadata, SFTConversationRecord, SFTPromptCompletionRecord
from tuneforge.validation.structural import StructuralValidationError, validate_structure, validate_token_length


def _metadata() -> RecordMetadata:
    return RecordMetadata(document_id=uuid.uuid4(), source_name="doc.md", source_hash="deadbeef")


class _FakeTokenizer:
    """Counts words as tokens — good enough to test the length-check logic
    without needing a real (network-downloaded) tokenizer.
    """

    def encode(self, text: str) -> list[int]:
        return text.split()


def test_valid_cpt_record_passes():
    validate_structure(CPTRecord(text="some real content", metadata=_metadata()))


def test_empty_cpt_record_fails():
    with pytest.raises(StructuralValidationError):
        validate_structure(CPTRecord(text="   ", metadata=_metadata()))


def test_valid_prompt_completion_record_passes():
    validate_structure(SFTPromptCompletionRecord(prompt="hi", completion="hello", metadata=_metadata()))


def test_empty_completion_fails():
    with pytest.raises(StructuralValidationError):
        validate_structure(SFTPromptCompletionRecord(prompt="hi", completion="  ", metadata=_metadata()))


def test_valid_conversation_passes():
    validate_structure(
        SFTConversationRecord(
            messages=[ChatMessage(role="user", content="hi"), ChatMessage(role="assistant", content="hello")],
            metadata=_metadata(),
        )
    )


def test_conversation_with_broken_role_order_fails():
    with pytest.raises(StructuralValidationError):
        validate_structure(
            SFTConversationRecord(
                messages=[ChatMessage(role="user", content="a"), ChatMessage(role="user", content="b")],
                metadata=_metadata(),
            )
        )


def test_valid_dpo_record_passes():
    validate_structure(
        DPORecord(
            prompt=[ChatMessage(role="user", content="q")],
            chosen=[ChatMessage(role="assistant", content="good")],
            rejected=[ChatMessage(role="assistant", content="bad")],
            metadata=_metadata(),
        )
    )


def test_dpo_record_with_empty_chosen_fails():
    with pytest.raises(StructuralValidationError):
        validate_structure(
            DPORecord(
                prompt=[ChatMessage(role="user", content="q")],
                chosen=[],
                rejected=[ChatMessage(role="assistant", content="bad")],
                metadata=_metadata(),
            )
        )


def test_record_within_token_limit_passes():
    record = CPTRecord(text="one two three", metadata=_metadata())
    validate_token_length(record, tokenizer=_FakeTokenizer(), max_tokens=10)


def test_record_over_token_limit_fails():
    record = CPTRecord(text="one two three four five", metadata=_metadata())
    with pytest.raises(StructuralValidationError):
        validate_token_length(record, tokenizer=_FakeTokenizer(), max_tokens=3)
