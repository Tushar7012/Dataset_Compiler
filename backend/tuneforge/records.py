from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, JsonValue


class SourceRecord(BaseModel):
    document_id: uuid.UUID
    chunk_id: str
    text: str
    source_name: str
    source_hash: str
    page: int | None
    heading: str | None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class RecordMetadata(BaseModel):
    document_id: uuid.UUID
    source_name: str
    source_hash: str
    chunk_id: str | None = None
    row_id: str | None = None
    source_kind: Literal["document", "structured"] = "document"
    extra: dict[str, JsonValue] = Field(default_factory=dict)


class CPTRecord(BaseModel):
    text: str
    metadata: RecordMetadata


class SFTPromptCompletionRecord(BaseModel):
    prompt: str
    completion: str
    metadata: RecordMetadata


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class SFTConversationRecord(BaseModel):
    messages: list[ChatMessage]
    metadata: RecordMetadata


class DPORecord(BaseModel):
    prompt: list[ChatMessage]
    chosen: list[ChatMessage]
    rejected: list[ChatMessage]
    metadata: RecordMetadata
