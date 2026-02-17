from datetime import datetime

from notion_format import build_notion_blocks


def _types(blocks):
    return [b.get("type") for b in blocks]


def test_dot_and_question_in_notes_are_reclassified():
    parsed = {
        "topics": [
            {
                "title": "Prosjekt",
                "tasks": [],
                "notes": [
                    ". gjør noe!!!",
                    "? 2. Hva skjer?",
                    "1. en vanlig nummerert note",
                ],
                "questions": [],
            }
        ]
    }

    blocks = build_notion_blocks(
        parsed=parsed,
        filename="IMG_0001.HEIC",
        image_upload_id=None,
        now=datetime(2026, 2, 17, 13, 0),
    )

    # Should contain one to_do for ". gjør noe!!!"
    todos = [b for b in blocks if b.get("type") == "to_do"]
    assert len(todos) == 1
    assert todos[0]["to_do"]["rich_text"][0]["text"]["content"] == "gjør noe!!!"
    assert todos[0]["to_do"]["checked"] is False

    # Should contain a question bullet without "2."
    q_bullets = [
        b for b in blocks
        if b.get("type") == "bulleted_list_item"
        and b["bulleted_list_item"]["rich_text"][0]["text"]["content"].startswith("❓ ")
    ]
    assert len(q_bullets) == 1
    assert q_bullets[0]["bulleted_list_item"]["rich_text"][0]["text"]["content"] == "❓ Hva skjer?"

    # The "1. ..." note should still become a numbered list item
    numbered = [b for b in blocks if b.get("type") == "numbered_list_item"]
    assert len(numbered) == 1
    assert numbered[0]["numbered_list_item"]["rich_text"][0]["text"]["content"] == "en vanlig nummerert note"
