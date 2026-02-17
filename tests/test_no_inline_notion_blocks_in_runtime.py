from pathlib import Path


def test_runtime_does_not_build_notion_blocks_inline():
    """
    Guardrail: All Notion block formatting must live in notion_format.py (build_notion_blocks),
    not inside the runtime menubar app. This prevents drift where tests no longer reflect runtime.
    """
    p = Path(__file__).resolve().parents[1] / "menubar_notes_to_notion.py"
    text = p.read_text("utf-8")

    # If someone later pastes Notion block dicts back into runtime, we want to catch it.
    forbidden_markers = [
        '"type": "heading_',
        '"type": "to_do"',
        '"type": "bulleted_list_item"',
        '"type": "numbered_list_item"',
        '"type": "divider"',
        '"type": "image"',
        '"type": "toggle"',
        '"type": "callout"',
    ]

    hits = [m for m in forbidden_markers if m in text]
    assert hits == [], f"Runtime contains inline Notion blocks markers: {hits}"
