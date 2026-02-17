from datetime import datetime
from notion_format import build_notion_blocks


def test_numbered_notes_become_numbered_list_items():
    parsed = {
        "topics": [{
            "title": "Test",
            "tasks": [],
            "notes": ["1. en", "2. to", "3. tre", "vanlig note"],
            "questions": []
        }]
    }

    blocks = build_notion_blocks(
        parsed,
        filename="IMG_1.HEIC",
        image_upload_id=None,
        now=datetime(2026, 2, 16, 23, 19),
    )

    numbered = [b for b in blocks if b.get("type") == "numbered_list_item"]
    assert [b["numbered_list_item"]["rich_text"][0]["text"]["content"] for b in numbered] == ["en", "to", "tre"]

    bullets = [b for b in blocks if b.get("type") == "bulleted_list_item"]
    assert any(b["bulleted_list_item"]["rich_text"][0]["text"]["content"] == "vanlig note" for b in bullets)


def test_tasks_render_as_todo_blocks():
    parsed = {
        "topics": [{
            "title": "Test",
            "tasks": [{"text": "oppgave", "done": False}, {"text": "ferdig", "done": True}],
            "notes": [],
            "questions": []
        }]
    }

    blocks = build_notion_blocks(
        parsed,
        filename="IMG_2.HEIC",
        image_upload_id=None,
        now=datetime(2026, 2, 16, 23, 19),
    )

    todos = [b for b in blocks if b.get("type") == "to_do"]
    assert len(todos) == 2
    assert todos[0]["to_do"]["rich_text"][0]["text"]["content"] == "oppgave"
    assert todos[0]["to_do"]["checked"] is False
    assert todos[1]["to_do"]["rich_text"][0]["text"]["content"] == "ferdig"
    assert todos[1]["to_do"]["checked"] is True


def test_questions_render_as_bullets_with_question_emoji():
    parsed = {
        "topics": [{
            "title": "Test",
            "tasks": [],
            "notes": [],
            "questions": ["et spørsmål"]
        }]
    }

    blocks = build_notion_blocks(
        parsed,
        filename="IMG_3.HEIC",
        image_upload_id=None,
        now=datetime(2026, 2, 16, 23, 19),
    )

    bullets = [b for b in blocks if b.get("type") == "bulleted_list_item"]
    assert any(
        b["bulleted_list_item"]["rich_text"][0]["text"]["content"] == "❓ et spørsmål"
        for b in bullets
    )


def test_image_block_included_when_upload_id_present_and_no_source_paragraph():
    parsed = {"topics": [{"title": "General", "tasks": [], "notes": ["note"], "questions": []}]}

    blocks = build_notion_blocks(
        parsed,
        filename="IMG_4.HEIC",
        image_upload_id="UPLOAD123",
        now=datetime(2026, 2, 16, 23, 19),
    )

    imgs = [b for b in blocks if b.get("type") == "image"]
    assert len(imgs) == 1
    assert imgs[0]["image"]["type"] == "file_upload"
    assert imgs[0]["image"]["file_upload"]["id"] == "UPLOAD123"

    # Ensure we do NOT include "Source: ..." paragraph when image is attached
    source_paras = [
        b for b in blocks
        if b.get("type") == "paragraph"
        and "paragraph" in b
        and b["paragraph"].get("rich_text")
        and b["paragraph"]["rich_text"][0].get("type") == "text"
        and b["paragraph"]["rich_text"][0]["text"]["content"].startswith("Source:")
    ]
    assert source_paras == []


def test_source_paragraph_included_when_no_image_upload_id():
    parsed = {"topics": [{"title": "General", "tasks": [], "notes": ["note"], "questions": []}]}

    blocks = build_notion_blocks(
        parsed,
        filename="IMG_5.HEIC",
        image_upload_id=None,
        now=datetime(2026, 2, 16, 23, 19),
    )

    source_paras = [
        b for b in blocks
        if b.get("type") == "paragraph"
        and "paragraph" in b
        and b["paragraph"].get("rich_text")
        and b["paragraph"]["rich_text"][0].get("type") == "text"
        and b["paragraph"]["rich_text"][0]["text"]["content"] == "Source: IMG_5.HEIC"
    ]
    assert len(source_paras) == 1