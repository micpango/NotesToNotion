import menubar_notes_to_notion as appmod


def test_chunking_updates_after_id(monkeypatch):
    calls = []

    class DummyNotion(appmod.NotionClient):
        def __init__(self): pass

        def append_children(self, block_id, children, after_block_id=None):
            calls.append(after_block_id)
            # Simulate Notion returning new block ids
            return {"results": [{"id": f"new_{len(calls)}"}]}

    pipeline = object.__new__(appmod.Pipeline)
    pipeline.notion = DummyNotion()
    pipeline.page_id = "PAGE"

    blocks = [{"object": "block"}] * 5
    after_id = "H1"
    chunk = 2

    for i in range(0, len(blocks), chunk):
        resp = pipeline.notion.append_children(pipeline.page_id, blocks[i:i + chunk], after_block_id=after_id)
        results = (resp or {}).get("results", []) or []
        if results and results[0].get("id"):
            after_id = results[0]["id"]

    assert calls == ["H1", "new_1", "new_2"]
