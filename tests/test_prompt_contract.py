from prompt_contract import PROMPT


def test_prompt_uses_dot_space_not_plain_dot():
    assert '". "' in PROMPT
    assert '"."' not in PROMPT


def test_prompt_defines_numbered_rule():
    assert '1. ' in PROMPT
    assert 'numbered note item' in PROMPT


def test_prompt_requires_prefix_space():
    assert 'must be first character' in PROMPT