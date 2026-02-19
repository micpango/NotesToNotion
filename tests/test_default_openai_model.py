import app_contract as ac


def test_default_openai_model_is_gpt_5_mini():
    assert ac.DEFAULT_OPENAI_MODEL == "gpt-5-mini"
