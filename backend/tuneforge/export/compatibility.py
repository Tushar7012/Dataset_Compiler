from __future__ import annotations

from tuneforge.records import SFTConversationRecord


def render_chat_template_sample(tokenizer, record: SFTConversationRecord) -> str:
    """Proves the target tokenizer can actually apply its chat template to
    a real conversational example from this dataset — not just that a
    chat_template key exists in tokenizer_config.json (Task 4 already
    checked that), but that applying it to real content doesn't raise.
    """
    messages = [{"role": m.role, "content": m.content} for m in record.messages]
    return tokenizer.apply_chat_template(messages, tokenize=False)


UNSLOTH_IMPORT_INSTRUCTIONS = """\
# Importing this dataset into Unsloth

This bundle contains `train.parquet` / `train.jsonl` and, if enough source
documents were available, `eval.parquet` / `eval.jsonl`. Load either format
with Hugging Face Datasets:

    from datasets import load_dataset
    dataset = load_dataset("parquet", data_files={"train": "train.parquet", "eval": "eval.parquet"})

Column mapping by objective (see `manifest.json` for which one this bundle is):

- `cpt` -> single `text` column, use as-is for continued pretraining.
- `sft_prompt_completion` -> `prompt` and `completion` columns.
- `sft_conversation` / `dpo` -> a `messages` (or `prompt`/`chosen`/`rejected`) column
  of `{"role": ..., "content": ...}` objects — apply your tokenizer's chat
  template before training, the same way `model-profile.json` confirms it renders.

See `validation-report.json` for the assurance level (`standard_assurance` vs
`lower_assurance`) and `provenance.jsonl` for per-row source traceability.
"""
