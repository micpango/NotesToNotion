from datetime import datetime

from notion_format import build_notion_blocks


def _h2_text(block):
    rt = block["heading_2"]["rich_text"]
    # rich_text is [mention, text(" — Title")]
    # we want the text part:
    text_parts = []
    for p in rt:
        if p.get("type") == "text":
            text_parts.append(p["text"]["content"])
    return "".join(text_parts)


def test_hash_starts_new_entry_and_title_is_without_hash():
    parsed = {
        "topics": [{
            "title": "General",
            "tasks": [{"text": "Follow up", "done": False}],
            "notes": ["#Ledermøte", "punkt 1", "#1:1 Fredrik", "punkt 2"],
            "questions": ["hva nå?"],
        }]
    }

    blocks = build_notion_blocks(
        parsed=parsed,
        filename="x.png",
        image_upload_id="file_upload_123",
        now=datetime(2026, 2, 17, 10, 0),
    )

    h2s = [b for b in blocks if b.get("type") == "heading_2"]
    assert len(h2s) == 2
    assert "Ledermøte" in _h2_text(h2s[0])
    assert "1:1 Fredrik" in _h2_text(h2s[1])

    # Ensure "#..." lines are not rendered as bullets
    bullets = [b for b in blocks if b.get("type") == "bulleted_list_item"]
    bullet_texts = [
        (b["bulleted_list_item"]["rich_text"][0]["text"]["content"] if b["bulleted_list_item"]["rich_text"] else "")
        for b in bullets
    ]
    assert not any(t.strip().startswith("#") for t in bullet_texts)


def test_empty_hash_section_is_ignored():
    parsed = {
        "topics": [{
            "title": "General",
            "tasks": [],
            "notes": ["#A", "#B", "note under B"],
            "questions": [],
        }]
    }

    blocks = build_notion_blocks(
        parsed=parsed,
        filename="x.png",
        image_upload_id=None,
        now=datetime(2026, 2, 17, 10, 0),
    )

    h2s = [b for b in blocks if b.get("type") == "heading_2"]
    assert len(h2s) == 1
    assert "B" in _h2_text(h2s[0])
