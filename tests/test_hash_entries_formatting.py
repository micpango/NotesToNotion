from datetime import datetime

from notion_format import build_notion_blocks


def _h2_blocks(blocks):
    return [b for b in blocks if b.get("type") == "heading_2"]


def _extract_h2_text(block):
    rt = block["heading_2"]["rich_text"]
    # First element is the date mention; the following text part contains " — <title>"
    # We assert on the text content only.
    return rt[1]["text"]["content"]


def test_single_hash_creates_single_h2_without_hash():
    parsed = {
        "topics": [
            {
                "title": "General",
                "tasks": [],
                "notes": [
                    "#Ledermøte",
                    "- agenda punkt",
                ],
                "questions": [],
            }
        ]
    }

    blocks = build_notion_blocks(
        parsed=parsed,
        filename="test.png",
        image_upload_id=None,
        now=datetime(2026, 1, 1, 10, 0),
    )

    h2s = _h2_blocks(blocks)

    # When hash entries exist, we do NOT create the default "Handwritten notes" entry.
    assert len(h2s) == 1

    txt = _extract_h2_text(h2s[0])
    assert "Ledermøte" in txt
    assert "#" not in txt


def test_multiple_hashes_create_multiple_entries():
    parsed = {
        "topics": [
            {
                "title": "General",
                "tasks": [],
                "notes": [
                    "#Ledermøte",
                    "- punkt 1",
                    "#1:1 Fredrik",
                    "- punkt 2",
                ],
                "questions": [],
            }
        ]
    }

    blocks = build_notion_blocks(
        parsed=parsed,
        filename="test.png",
        image_upload_id=None,
        now=datetime(2026, 1, 1, 10, 0),
    )

    h2s = _h2_blocks(blocks)

    # Only the hash entries become H2s
    assert len(h2s) == 2

    texts = [_extract_h2_text(b) for b in h2s]

    assert any("Ledermøte" in t for t in texts)
    assert any("1:1 Fredrik" in t for t in texts)


def test_content_between_hashes_is_grouped_correctly():
    parsed = {
        "topics": [
            {
                "title": "General",
                "tasks": [],
                "notes": [
                    "#Ledermøte",
                    "- A",
                    "- B",
                    "#Retrospektiv",
                    "- C",
                ],
                "questions": [],
            }
        ]
    }

    blocks = build_notion_blocks(
        parsed=parsed,
        filename="test.png",
        image_upload_id=None,
        now=datetime(2026, 1, 1, 10, 0),
    )

    # find all H2 indices
    h2_indices = [i for i, b in enumerate(blocks) if b.get("type") == "heading_2"]

    # Only the hash entries become H2s
    assert len(h2_indices) == 2

    assert "Ledermøte" in _extract_h2_text(blocks[h2_indices[0]])
    assert "Retrospektiv" in _extract_h2_text(blocks[h2_indices[1]])