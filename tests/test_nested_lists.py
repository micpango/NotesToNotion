from datetime import datetime

from notion_format import build_notion_blocks


def _top_list_blocks(blocks):
    return [b for b in blocks if b.get("type") in {"bulleted_list_item", "numbered_list_item"}]


def _block_text(block):
    block_type = block["type"]
    rich_text = (block.get(block_type) or {}).get("rich_text") or []
    if not rich_text:
        return ""
    return ((rich_text[0].get("text") or {}).get("content") or "")


def _children(block):
    block_type = block["type"]
    return (block.get(block_type) or {}).get("children") or []


def _render_notes(notes):
    parsed = {
        "topics": [{
            "title": "General",
            "tasks": [],
            "notes": notes,
            "questions": [],
        }]
    }
    return build_notion_blocks(
        parsed=parsed,
        filename="IMG_1.HEIC",
        image_upload_id=None,
        now=datetime(2026, 2, 16, 23, 19),
        include_entry_heading=False,
    )


def test_spaced_nested_bullets():
    blocks = _render_notes(["- A", "- - B", "- - - C", "- D"])
    top = _top_list_blocks(blocks)

    assert [b["type"] for b in top] == ["bulleted_list_item", "bulleted_list_item"]
    assert [_block_text(b) for b in top] == ["A", "D"]

    a_children = _children(top[0])
    assert len(a_children) == 1
    assert _block_text(a_children[0]) == "B"

    b_children = _children(a_children[0])
    assert len(b_children) == 1
    assert _block_text(b_children[0]) == "C"


def test_compact_nested_bullets():
    blocks = _render_notes(["- A", "-- B", "--- C", "- D"])
    top = _top_list_blocks(blocks)

    assert [b["type"] for b in top] == ["bulleted_list_item", "bulleted_list_item"]
    assert [_block_text(b) for b in top] == ["A", "D"]

    a_children = _children(top[0])
    assert len(a_children) == 1
    assert _block_text(a_children[0]) == "B"

    b_children = _children(a_children[0])
    assert len(b_children) == 1
    assert _block_text(b_children[0]) == "C"


def test_nested_numbered():
    blocks = _render_notes(["1. A", "1.1 B", "1.1.1 C", "2. D"])
    top = _top_list_blocks(blocks)

    assert [b["type"] for b in top] == ["numbered_list_item", "numbered_list_item"]
    assert [_block_text(b) for b in top] == ["A", "D"]

    a_children = _children(top[0])
    assert len(a_children) == 1
    assert _block_text(a_children[0]) == "B"

    b_children = _children(a_children[0])
    assert len(b_children) == 1
    assert _block_text(b_children[0]) == "C"


def test_mixed_sequences():
    blocks = _render_notes(["- A", "-- B", "1. C", "1.1 D"])
    top = _top_list_blocks(blocks)

    assert [b["type"] for b in top] == ["bulleted_list_item", "numbered_list_item"]
    assert [_block_text(b) for b in top] == ["A", "C"]

    a_children = _children(top[0])
    assert len(a_children) == 1
    assert _block_text(a_children[0]) == "B"

    c_children = _children(top[1])
    assert len(c_children) == 1
    assert _block_text(c_children[0]) == "D"


def test_invalid_jump_clamped():
    blocks = _render_notes(["- A", "- - - C"])
    top = _top_list_blocks(blocks)

    assert [_block_text(b) for b in top] == ["A"]
    a_children = _children(top[0])
    assert len(a_children) == 1
    assert _block_text(a_children[0]) == "C"
    assert _children(a_children[0]) == []


def test_complex_nested_sequence():
    blocks = _render_notes(["- A", "- - B", "- - - C", "- D", "- - E"])
    top = _top_list_blocks(blocks)

    assert [_block_text(b) for b in top] == ["A", "D"]

    a_children = _children(top[0])
    assert len(a_children) == 1
    assert _block_text(a_children[0]) == "B"

    b_children = _children(a_children[0])
    assert len(b_children) == 1
    assert _block_text(b_children[0]) == "C"

    d_children = _children(top[1])
    assert len(d_children) == 1
    assert _block_text(d_children[0]) == "E"
