from tuneforge.normalization.detector import DetectedSchema, detect_schema


def test_detects_text_schema():
    result = detect_schema([{"text": "hello world"}])
    assert result.schema_name == DetectedSchema.TEXT


def test_detects_prompt_completion_schema():
    result = detect_schema([{"prompt": "hi", "completion": "hello"}])
    assert result.schema_name == DetectedSchema.PROMPT_COMPLETION


def test_detects_instruction_input_output_schema():
    result = detect_schema([{"instruction": "summarize", "input": "text", "output": "summary"}])
    assert result.schema_name == DetectedSchema.INSTRUCTION_INPUT_OUTPUT


def test_detects_messages_schema():
    result = detect_schema([{"messages": [{"role": "user", "content": "hi"}]}])
    assert result.schema_name == DetectedSchema.MESSAGES


def test_detects_conversations_schema():
    result = detect_schema([{"conversations": [{"from": "human", "value": "hi"}]}])
    assert result.schema_name == DetectedSchema.CONVERSATIONS


def test_detects_prompt_chosen_rejected_schema():
    result = detect_schema([{"prompt": "q", "chosen": "good", "rejected": "bad"}])
    assert result.schema_name == DetectedSchema.PROMPT_CHOSEN_REJECTED


def test_prompt_chosen_rejected_takes_priority_over_prompt_completion():
    # A row with all five keys is unambiguously DPO-shaped, not SFT-shaped.
    result = detect_schema([{"prompt": "q", "completion": "x", "chosen": "good", "rejected": "bad"}])
    assert result.schema_name == DetectedSchema.PROMPT_CHOSEN_REJECTED


def test_unrecognized_columns_return_none_not_a_guess():
    result = detect_schema([{"question": "hi", "answer": "hello"}])
    assert result.schema_name is None
    assert result.confidence == 0.0


def test_empty_rows_return_none():
    result = detect_schema([])
    assert result.schema_name is None
