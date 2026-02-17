import prompt_contract as pc


def test_hash_rule_is_present_in_prompt():
    """
    Guardrail test: ensure the '#' entry rule is documented in the prompt.
    This prevents accidental regression if the prompt is edited later.
    """

    prompt = pc.PROMPT

    # Core behavior must be described
    assert '# ' in prompt
    assert 'start of a NEW entry' in prompt

    # We must explicitly preserve the hash
    assert 'Preserve the entire line INCLUDING the leading "#"' in prompt

    # Must clarify multiple entries per image are allowed
    assert 'multiple "# ..."' in prompt
