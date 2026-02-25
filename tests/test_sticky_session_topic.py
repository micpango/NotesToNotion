import menubar_notes_to_notion as appmod


def _pipeline():
    return appmod.Pipeline(
        openai_key="x",
        model="gpt-5-mini",
        notion_token="y",
        page_id="PAGEID",
        status_cb=lambda _msg: None,
    )


def test_first_image_with_hash_topic_sets_session():
    p = _pipeline()
    parsed = {
        "topics": [{"title": "General", "tasks": [], "notes": ["# Ledermote"], "questions": []}]
    }

    out = p.apply_sticky_session_topic(parsed, now_ts=1000.0)

    assert out["topics"][0]["notes"][0] == "# Ledermote"
    assert p.active_topic == "Ledermote"
    assert p.active_until == 1300.0


def test_second_image_without_hash_within_ttl_uses_same_topic():
    p = _pipeline()
    p.active_topic = "Ledermote"
    p.active_until = 1300.0
    parsed = {
        "topics": [{"title": "General", "tasks": [], "notes": ["punkt"], "questions": []}]
    }

    out = p.apply_sticky_session_topic(parsed, now_ts=1100.0)

    assert out["topics"][0]["notes"][0] == "# Ledermote"


def test_image_after_ttl_falls_back_to_default():
    p = _pipeline()
    p.active_topic = "Ledermote"
    p.active_until = 1000.0
    parsed = {
        "topics": [{"title": "General", "tasks": [], "notes": ["punkt"], "questions": []}]
    }

    out = p.apply_sticky_session_topic(parsed, now_ts=1301.0)

    assert out["topics"][0]["notes"][0] == "punkt"


def test_new_hash_topic_overrides_previous_session():
    p = _pipeline()
    p.active_topic = "OldTopic"
    p.active_until = 2000.0
    parsed = {
        "topics": [{"title": "General", "tasks": [], "notes": ["# NewTopic"], "questions": []}]
    }

    out = p.apply_sticky_session_topic(parsed, now_ts=1500.0)

    assert out["topics"][0]["notes"][0] == "# NewTopic"
    assert p.active_topic == "NewTopic"
    assert p.active_until == 1800.0
