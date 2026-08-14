from __future__ import annotations

import uuid

from docling.chunking import HybridChunker
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.types.doc.document import DoclingDocument
from transformers import AutoTokenizer

from tuneforge.records import SourceRecord

DEFAULT_MAX_TOKENS_PER_CHUNK = 512


def build_tokenizer(model_id: str, *, max_tokens: int = DEFAULT_MAX_TOKENS_PER_CHUNK) -> HuggingFaceTokenizer:
    """Wraps the *target model's own* tokenizer for HybridChunker, so chunk
    boundaries are measured in the tokens that model will actually see —
    not some fixed character count that has nothing to do with its context
    window.
    """
    hf_tokenizer = AutoTokenizer.from_pretrained(model_id)
    return HuggingFaceTokenizer(tokenizer=hf_tokenizer, max_tokens=max_tokens)


def chunk_into_source_records(
    document: DoclingDocument,
    *,
    document_id: uuid.UUID,
    source_name: str,
    source_hash: str,
    tokenizer: HuggingFaceTokenizer,
) -> list[SourceRecord]:
    chunker = HybridChunker(tokenizer=tokenizer)
    records = []
    for index, chunk in enumerate(chunker.chunk(dl_doc=document)):
        page = None
        for doc_item in chunk.meta.doc_items:
            if doc_item.prov:
                page = doc_item.prov[0].page_no
                break
        heading = chunk.meta.headings[-1] if chunk.meta.headings else None
        records.append(
            SourceRecord(
                document_id=document_id,
                chunk_id=f"{document_id}-{index}",
                text=chunk.text,
                source_name=source_name,
                source_hash=source_hash,
                page=page,
                heading=heading,
                metadata={"headings": list(chunk.meta.headings)},
            )
        )
    return records
