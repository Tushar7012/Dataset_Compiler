from transformers import AutoTokenizer

from tuneforge.export.compatibility import UNSLOTH_IMPORT_INSTRUCTIONS, render_chat_template_sample
from tuneforge.records import ChatMessage, RecordMetadata, SFTConversationRecord
import uuid


def _conversation_record() -> SFTConversationRecord:
    return SFTConversationRecord(
        messages=[ChatMessage(role="user", content="Hi"), ChatMessage(role="assistant", content="Hello!")],
        metadata=RecordMetadata(document_id=uuid.uuid4(), source_name="doc.md", source_hash="deadbeef"),
    )


def test_render_chat_template_sample_produces_nonempty_text_for_a_chat_model():
    # Requires a tokenizer with a real chat_template. If this specific
    # tokenizer changes its template format upstream, swap it for another
    # small chat-capable model rather than deleting the test.
    tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-0.5B-Instruct")

    rendered = render_chat_template_sample(tokenizer, _conversation_record())

    assert isinstance(rendered, str)
    assert "Hello!" in rendered or "Hi" in rendered


def test_render_chat_template_sample_raises_a_clear_error_without_a_template():
    tokenizer = AutoTokenizer.from_pretrained("gpt2")  # base model, no chat_template

    try:
        render_chat_template_sample(tokenizer, _conversation_record())
        raised = False
    except Exception:
        raised = True
    assert raised, "a tokenizer with no chat_template should fail clearly, not silently"


def test_unsloth_instructions_mention_the_export_file_names():
    assert "train.parquet" in UNSLOTH_IMPORT_INSTRUCTIONS
    assert "eval.parquet" in UNSLOTH_IMPORT_INSTRUCTIONS
