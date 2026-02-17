from datetime import datetime

from notion_format import build_notion_blocks


def test_no_empty_paragraph_spacers():
    parsed = {
        "topics": [
            {"title": "A", "tasks": [], "notes": [], "questions": []},
            {"title": "B", "tasks": [], "notes": [], "questions": []},
        ]
    }

    blocks = build_notion_blocks(
        parsed=parsed,
        filename="x",
        image_upload_id=None,
        now=datetime(2026, 2, 16, 23, 19),
    )

    # Assert there are no empty paragraph blocks
    for b in blocks:
        if b.get("type") == "paragraph":
            rt = (b.get("paragraph") or {}).get("rich_text") or []
            assert not (len(rt) == 1 and rt[0].get("type") == "text" and rt[0]["text"].get("content") == "")
