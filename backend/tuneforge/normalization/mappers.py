from __future__ import annotations

import uuid

from tuneforge.ingestion.structured import StructuredRow
from tuneforge.normalization.detector import DetectedSchema
from tuneforge.records import (
    ChatMessage,
    CPTRecord,
    DPORecord,
    RecordMetadata,
    SFTConversationRecord,
    SFTPromptCompletionRecord,
)
from tuneforge.validation.structural import StructuralValidationError
from tuneforge.validation.structural import validate_role_alternation as _shared_validate_role_alternation


class InvalidRecordError(RuntimeError):
    pass


def _metadata(row: StructuredRow, document_id: uuid.UUID) -> RecordMetadata:
    return RecordMetadata(
        document_id=document_id,
        source_name=row.source_name,
        source_hash=row.source_hash,
        row_id=row.row_id,
        source_kind="structured",
    )


def _require_nonempty_str(row: StructuredRow, field: str) -> str:
    value = row.data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise InvalidRecordError(f"row {row.row_id}: {field!r} must be a non-empty string")
    return value


def _validate_role_alternation(messages: list[ChatMessage]) -> None:
    # Shared with the validation pipeline (Task 10) — same algorithm, one
    # place it lives. Translated back to this module's own exception type
    # so callers here don't need to know about tuneforge.validation.
    try:
        _shared_validate_role_alternation(messages)
    except StructuralValidationError as exc:
        raise InvalidRecordError(str(exc)) from exc


def normalize_text_row(row: StructuredRow, *, document_id: uuid.UUID) -> CPTRecord:
    return CPTRecord(text=_require_nonempty_str(row, "text"), metadata=_metadata(row, document_id))


def normalize_prompt_completion_row(row: StructuredRow, *, document_id: uuid.UUID) -> SFTPromptCompletionRecord:
    return SFTPromptCompletionRecord(
        prompt=_require_nonempty_str(row, "prompt"),
        completion=_require_nonempty_str(row, "completion"),
        metadata=_metadata(row, document_id),
    )


def normalize_instruction_row(row: StructuredRow, *, document_id: uuid.UUID) -> SFTPromptCompletionRecord:
    instruction = _require_nonempty_str(row, "instruction")
    output = _require_nonempty_str(row, "output")
    input_text = row.data.get("input") or ""
    prompt = f"{instruction}\n\n{input_text}".strip() if input_text else instruction
    return SFTPromptCompletionRecord(prompt=prompt, completion=output, metadata=_metadata(row, document_id))


def normalize_messages_row(row: StructuredRow, *, document_id: uuid.UUID) -> SFTConversationRecord:
    raw_messages = row.data.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        raise InvalidRecordError(f"row {row.row_id}: 'messages' must be a non-empty list")
    try:
        messages = [ChatMessage(role=m["role"], content=m["content"]) for m in raw_messages]
    except (KeyError, TypeError) as exc:
        raise InvalidRecordError(f"row {row.row_id}: each message needs 'role' and 'content'") from exc
    _validate_role_alternation(messages)
    return SFTConversationRecord(messages=messages, metadata=_metadata(row, document_id))


_CONVERSATIONS_ROLE_MAP = {"human": "user", "gpt": "assistant", "system": "system"}


def normalize_conversations_row(row: StructuredRow, *, document_id: uuid.UUID) -> SFTConversationRecord:
    raw_turns = row.data.get("conversations")
    if not isinstance(raw_turns, list) or not raw_turns:
        raise InvalidRecordError(f"row {row.row_id}: 'conversations' must be a non-empty list")
    messages = []
    for turn in raw_turns:
        sender = turn.get("from")
        role = _CONVERSATIONS_ROLE_MAP.get(sender)
        if role is None:
            raise InvalidRecordError(f"row {row.row_id}: unknown conversation sender {sender!r}")
        messages.append(ChatMessage(role=role, content=turn["value"]))
    _validate_role_alternation(messages)
    return SFTConversationRecord(messages=messages, metadata=_metadata(row, document_id))


def normalize_dpo_row(row: StructuredRow, *, document_id: uuid.UUID) -> DPORecord:
    prompt = _require_nonempty_str(row, "prompt")
    chosen = _require_nonempty_str(row, "chosen")
    rejected = _require_nonempty_str(row, "rejected")
    return DPORecord(
        prompt=[ChatMessage(role="user", content=prompt)],
        chosen=[ChatMessage(role="assistant", content=chosen)],
        rejected=[ChatMessage(role="assistant", content=rejected)],
        metadata=_metadata(row, document_id),
    )


NORMALIZERS = {
    DetectedSchema.TEXT: normalize_text_row,
    DetectedSchema.PROMPT_COMPLETION: normalize_prompt_completion_row,
    DetectedSchema.INSTRUCTION_INPUT_OUTPUT: normalize_instruction_row,
    DetectedSchema.MESSAGES: normalize_messages_row,
    DetectedSchema.CONVERSATIONS: normalize_conversations_row,
    DetectedSchema.PROMPT_CHOSEN_REJECTED: normalize_dpo_row,
}

# What canonical record class each detected schema normalizes to — the same
# strings as planning.planner.CANONICAL_SCHEMA_BY_OBJECTIVE, so a run can check
# "does this structured source's detected schema match the plan's objective"
# before merging it in, instead of silently mixing incompatible record shapes.
CANONICAL_SCHEMA_BY_DETECTED_SCHEMA: dict[DetectedSchema, str] = {
    DetectedSchema.TEXT: "CPTRecord",
    DetectedSchema.PROMPT_COMPLETION: "SFTPromptCompletionRecord",
    DetectedSchema.INSTRUCTION_INPUT_OUTPUT: "SFTPromptCompletionRecord",
    DetectedSchema.MESSAGES: "SFTConversationRecord",
    DetectedSchema.CONVERSATIONS: "SFTConversationRecord",
    DetectedSchema.PROMPT_CHOSEN_REJECTED: "DPORecord",
}


def normalize_rows(rows: list[StructuredRow], schema: DetectedSchema, *, document_id: uuid.UUID) -> list:
    normalizer = NORMALIZERS[schema]
    return [normalizer(row, document_id=document_id) for row in rows]
