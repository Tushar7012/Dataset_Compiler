from __future__ import annotations

from tuneforge.records import ChatMessage, CPTRecord, DPORecord, SFTConversationRecord, SFTPromptCompletionRecord


class StructuralValidationError(RuntimeError):
    pass


def validate_role_alternation(messages: list[ChatMessage]) -> None:
    if not messages:
        raise StructuralValidationError("conversation has no messages")
    non_system = [m for m in messages if m.role != "system"]
    if not non_system:
        raise StructuralValidationError("conversation has only a system message")
    if non_system[0].role != "user":
        raise StructuralValidationError("conversation must start with a user message (after any system message)")
    for previous, current in zip(non_system, non_system[1:]):
        if previous.role == current.role:
            raise StructuralValidationError(f"consecutive {current.role!r} messages — roles must alternate")


def validate_structure(record) -> None:
    """Schema-appropriate non-empty checks + role alternation for chat-shaped
    records. Pydantic already enforces field *types*; this catches
    technically-valid-but-useless content (empty strings) that types alone
    don't rule out.
    """
    if isinstance(record, CPTRecord):
        if not record.text.strip():
            raise StructuralValidationError("CPT record has empty text")
    elif isinstance(record, SFTPromptCompletionRecord):
        if not record.prompt.strip() or not record.completion.strip():
            raise StructuralValidationError("SFT prompt/completion record has an empty field")
    elif isinstance(record, SFTConversationRecord):
        if any(not m.content.strip() for m in record.messages):
            raise StructuralValidationError("conversation has an empty message")
        validate_role_alternation(record.messages)
    elif isinstance(record, DPORecord):
        for field_name, messages in (("prompt", record.prompt), ("chosen", record.chosen), ("rejected", record.rejected)):
            if not messages or any(not m.content.strip() for m in messages):
                raise StructuralValidationError(f"DPO record has an empty {field_name!r}")
    else:
        raise StructuralValidationError(f"unrecognized record type: {type(record).__name__}")


def render_record_text(record) -> str:
    """Flattens any canonical record to plain text — shared by token-length
    checking, deduplication, and judging, which all need "the text of this
    record" but don't care about the schema differences otherwise.
    """
    if isinstance(record, CPTRecord):
        return record.text
    if isinstance(record, SFTPromptCompletionRecord):
        return f"{record.prompt}\n{record.completion}"
    if isinstance(record, SFTConversationRecord):
        return "\n".join(m.content for m in record.messages)
    if isinstance(record, DPORecord):
        return "\n".join(m.content for m in record.prompt + record.chosen + record.rejected)
    raise StructuralValidationError(f"unrecognized record type: {type(record).__name__}")


def validate_token_length(record, *, tokenizer, max_tokens: int) -> None:
    token_count = len(tokenizer.encode(render_record_text(record)))
    if token_count > max_tokens:
        raise StructuralValidationError(f"record renders to {token_count} tokens, exceeding the {max_tokens} limit")
