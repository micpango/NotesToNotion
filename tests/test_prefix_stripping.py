from datetime import datetime

from notion_format import build_notion_blocks


def _bullets(blocks):
    return [b for b in blocks if b.get("type") == "bulleted_list_item"]


def test_note_dash_prefix_is_stripped():
    parsed = {
        "topics": [{
            "title": "T",
            "tasks": [],
            "notes": ["- et notat"],
            "questions": []
        }]
    }

    blocks = build_notion_blocks(
        parsed=parsed,
        filename="x",
        image_upload_id=None,
        now=datetime(2026, 2, 16, 23, 19),
    )

    bullets = _bullets(blocks)
    assert any(
        b["bulleted_list_item"]["rich_text"][0]["text"]["content"] == "et notat"
        for b in bullets
    )


def test_question_prefix_is_stripped_but_emoji_is_kept():
    parsed = {
        "topics": [{
            "title": "T",
            "tasks": [],
            "notes": [],
            "questions": ["? et spørsmål"]
        }]
    }

    blocks = build_notion_blocks(
        parsed=parsed,
        filename="x",
        image_upload_id=None,
        now=datetime(2026, 2, 16, 23, 19),
    )

    bullets = _bullets(blocks)
    assert any(
        b["bulleted_list_item"]["rich_text"][0]["text"]["content"] == "❓ et spørsmål"
        for b in bullets
    )
