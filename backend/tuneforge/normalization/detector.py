from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class DetectedSchema(StrEnum):
    TEXT = "text"
    PROMPT_COMPLETION = "prompt_completion"
    INSTRUCTION_INPUT_OUTPUT = "instruction_input_output"
    MESSAGES = "messages"
    CONVERSATIONS = "conversations"
    PROMPT_CHOSEN_REJECTED = "prompt_chosen_rejected"


class SchemaDetectionResult(BaseModel):
    schema_name: DetectedSchema | None
    confidence: float
    matched_keys: list[str]


def detect_schema(rows: list[dict]) -> SchemaDetectionResult:
    """Exact-key matching only — deliberately not fuzzy. This is meant to
    recognize obvious, common shapes without guessing; anything that
    doesn't match exactly falls back to manual column mapping rather than
    a low-confidence guess that might be wrong.
    """
    if not rows:
        return SchemaDetectionResult(schema_name=None, confidence=0.0, matched_keys=[])

    keys = set(rows[0].keys())

    if {"prompt", "chosen", "rejected"} <= keys:
        return SchemaDetectionResult(
            schema_name=DetectedSchema.PROMPT_CHOSEN_REJECTED, confidence=1.0, matched_keys=["prompt", "chosen", "rejected"]
        )
    if "messages" in keys and isinstance(rows[0].get("messages"), list):
        return SchemaDetectionResult(schema_name=DetectedSchema.MESSAGES, confidence=1.0, matched_keys=["messages"])
    if "conversations" in keys and isinstance(rows[0].get("conversations"), list):
        return SchemaDetectionResult(
            schema_name=DetectedSchema.CONVERSATIONS, confidence=1.0, matched_keys=["conversations"]
        )
    if {"prompt", "completion"} <= keys:
        return SchemaDetectionResult(
            schema_name=DetectedSchema.PROMPT_COMPLETION, confidence=1.0, matched_keys=["prompt", "completion"]
        )
    if {"instruction", "output"} <= keys:
        return SchemaDetectionResult(
            schema_name=DetectedSchema.INSTRUCTION_INPUT_OUTPUT, confidence=1.0, matched_keys=["instruction", "output"]
        )
    if "text" in keys and isinstance(rows[0].get("text"), str):
        return SchemaDetectionResult(schema_name=DetectedSchema.TEXT, confidence=1.0, matched_keys=["text"])

    return SchemaDetectionResult(schema_name=None, confidence=0.0, matched_keys=[])
