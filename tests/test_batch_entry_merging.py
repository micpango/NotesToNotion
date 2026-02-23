from pathlib import Path

import menubar_notes_to_notion as appmod


def _h2_title(block):
    rt = ((block.get("heading_2") or {}).get("rich_text") or [])
    return "".join(
        ((p.get("text") or {}).get("content") or "")
        for p in rt
        if p.get("type") == "text"
    )


class _FakeNotion:
    def __init__(self):
        self.calls = []
        self._n = 0

    def upload_image_bytes(self, filename, data, content_type="image/jpeg"):
        return "UPLOAD123"

    def find_first_h1_id(self, page_id, page_size=50):
        return "H1BLOCK"

    def list_children_ids(self, block_id, page_size=50):
        return ["FIRSTCHILD"]

    def append_children(self, block_id, children, after_block_id=None):
        self.calls.append({"block_id": block_id, "after": after_block_id, "children": children})
        results = []
        for c in children:
            self._n += 1
            res = {"id": f"id-{self._n}"}
            if c.get("type"):
                res["type"] = c.get("type")
            results.append(res)
        return {"results": results}

    def resolve_parent_page_id(self, block_id):
        return "11111111-2222-3333-4444-555555555555"


def _make_pipeline(monkeypatch, tmp_path: Path, parsed_by_name: dict):
    monkeypatch.setattr(appmod, "USAGE_PATH", tmp_path / "usage.json")
    monkeypatch.setattr(appmod.Pipeline, "seen", lambda self, fp: False)
    monkeypatch.setattr(appmod.Pipeline, "mark", lambda self, fp, name: None)
    monkeypatch.setattr(appmod, "image_to_jpeg_bytes", lambda p: b"jpeg")
    monkeypatch.setattr(appmod, "notify_processed_image", lambda *args, **kwargs: None)
    monkeypatch.setattr(appmod.time, "sleep", lambda _n: None)

    p = appmod.Pipeline(
        openai_key="x",
        model="gpt-5-mini",
        notion_token="y",
        page_id="PAGEID",
        status_cb=lambda _msg: None,
    )
    p.notion = _FakeNotion()
    monkeypatch.setattr(
        appmod.Pipeline,
        "transcribe_from_jpeg",
        lambda self, jpeg, filename: parsed_by_name[filename],
    )
    monkeypatch.setattr(appmod.Pipeline, "record_usage", lambda self, filename: None)
    return p


def _flatten_children(calls):
    out = []
    for call in calls:
        out.extend(call["children"])
    return out


def _set_mtime(path: Path, ts: float):
    import os
    os.utime(path, (ts, ts))


def test_inherit_meeting_title_within_batch_window_when_no_hash(monkeypatch, tmp_path):
    p = _make_pipeline(monkeypatch, tmp_path, {})
    p.start_batch(ignore_window=False)
    try:
        parsed1 = {"topics": [{"title": "General", "tasks": [], "notes": ["# Ledermote"], "questions": []}]}
        parsed2 = {"topics": [{"title": "General", "tasks": [], "notes": ["punkt"], "questions": []}]}
        start_new, inherit, title = p._effective_entry_for_file(parsed1, 1000.0)
        assert (start_new, inherit, title) == (True, False, "Ledermote")
        p.batch_ctx.active_entry_title = title
        p.batch_ctx.last_file_mtime = 1000.0
        start_new, inherit, title = p._effective_entry_for_file(parsed2, 1060.0)
        assert (start_new, inherit, title) == (False, True, "Ledermote")
    finally:
        p.end_batch()


def test_new_hash_starts_new_meeting_even_within_batch_window(monkeypatch, tmp_path):
    p = _make_pipeline(monkeypatch, tmp_path, {})
    p.start_batch(ignore_window=False)
    try:
        p.batch_ctx.active_entry_title = "Ledermote"
        p.batch_ctx.last_file_mtime = 1000.0
        parsed = {"topics": [{"title": "General", "tasks": [], "notes": ["# OLG Test"], "questions": []}]}
        start_new, inherit, title = p._effective_entry_for_file(parsed, 1050.0)
        assert (start_new, inherit, title) == (True, False, "OLG Test")
    finally:
        p.end_batch()


def test_no_hash_outside_window_falls_back_to_default(monkeypatch, tmp_path):
    p = _make_pipeline(monkeypatch, tmp_path, {})
    p.start_batch(ignore_window=False)
    try:
        p.batch_ctx.active_entry_title = "Ledermote"
        p.batch_ctx.last_file_mtime = 1000.0
        parsed = {"topics": [{"title": "General", "tasks": [], "notes": ["punkt"], "questions": []}]}
        start_new, inherit, title = p._effective_entry_for_file(parsed, 2000.0)
        assert (start_new, inherit, title) == (True, False, "Handwritten notes")
    finally:
        p.end_batch()


def test_batch_hash_then_two_nohash_merges_under_one_entry(monkeypatch, tmp_path):
    parsed = {
        "a.png": {"topics": [{"title": "General", "tasks": [], "notes": ["# A", "n1"], "questions": []}]},
        "b.png": {"topics": [{"title": "General", "tasks": [], "notes": ["n2"], "questions": []}]},
        "c.png": {"topics": [{"title": "General", "tasks": [], "notes": ["n3"], "questions": []}]},
    }
    p = _make_pipeline(monkeypatch, tmp_path, parsed)
    notified_titles = []
    monkeypatch.setattr(
        appmod,
        "notify_processed_image",
        lambda section_title, filename, url: notified_titles.append(section_title),
    )

    p.start_batch(ignore_window=False)
    try:
        t0 = 1700000000.0
        for idx, name in enumerate(["a.png", "b.png", "c.png"]):
            path = tmp_path / name
            path.write_bytes(b"x")
            _set_mtime(path, t0 + (idx * 30))
            p.process(path)
    finally:
        p.end_batch()

    children = _flatten_children(p.notion.calls)
    h2s = [b for b in children if b.get("type") == "heading_2"]
    images = [b for b in children if b.get("type") == "image"]
    bullets = [b for b in children if b.get("type") == "bulleted_list_item"]
    bullet_texts = [
        (((b.get("bulleted_list_item") or {}).get("rich_text") or [{}])[0].get("text") or {}).get("content", "")
        for b in bullets
    ]

    assert len(h2s) == 1
    assert len(images) == 3
    assert not any(t.strip().startswith("#") for t in bullet_texts)
    assert p.notion.calls[0]["block_id"] == "PAGEID"
    assert p.notion.calls[1]["block_id"] == "id-1"
    assert p.notion.calls[2]["block_id"] == "id-1"
    assert notified_titles == ["A", "A", "A"]


def test_batch_hash_nohash_hash_nohash_creates_two_entries(monkeypatch, tmp_path):
    parsed = {
        "a.png": {"topics": [{"title": "General", "tasks": [], "notes": ["# A", "n1"], "questions": []}]},
        "b.png": {"topics": [{"title": "General", "tasks": [], "notes": ["n2"], "questions": []}]},
        "c.png": {"topics": [{"title": "General", "tasks": [], "notes": ["# B", "n3"], "questions": []}]},
        "d.png": {"topics": [{"title": "General", "tasks": [], "notes": ["n4"], "questions": []}]},
    }
    p = _make_pipeline(monkeypatch, tmp_path, parsed)

    p.start_batch(ignore_window=False)
    try:
        t0 = 1700000000.0
        for idx, name in enumerate(["a.png", "b.png", "c.png", "d.png"]):
            path = tmp_path / name
            path.write_bytes(b"x")
            _set_mtime(path, t0 + (idx * 30))
            p.process(path)
    finally:
        p.end_batch()

    h2s = [b for b in _flatten_children(p.notion.calls) if b.get("type") == "heading_2"]
    titles = [_h2_title(b) for b in h2s]
    assert len(h2s) == 2
    assert any("A" in t for t in titles)
    assert any("B" in t for t in titles)


def test_batch_starts_without_hash_then_hash_splits_entries(monkeypatch, tmp_path):
    parsed = {
        "a.png": {"topics": [{"title": "General", "tasks": [], "notes": ["n1"], "questions": []}]},
        "b.png": {"topics": [{"title": "General", "tasks": [], "notes": ["n2"], "questions": []}]},
        "c.png": {"topics": [{"title": "General", "tasks": [], "notes": ["# B", "n3"], "questions": []}]},
        "d.png": {"topics": [{"title": "General", "tasks": [], "notes": ["n4"], "questions": []}]},
    }
    p = _make_pipeline(monkeypatch, tmp_path, parsed)

    p.start_batch(ignore_window=True)
    try:
        t0 = 1700000000.0
        for idx, name in enumerate(["a.png", "b.png", "c.png", "d.png"]):
            path = tmp_path / name
            path.write_bytes(b"x")
            _set_mtime(path, t0 + (idx * 400))
            p.process(path)
    finally:
        p.end_batch()

    h2s = [b for b in _flatten_children(p.notion.calls) if b.get("type") == "heading_2"]
    titles = [_h2_title(b) for b in h2s]
    assert len(h2s) == 2
    assert any("Handwritten notes" in t for t in titles)
    assert any("B" in t for t in titles)


def test_append_plan_reuses_same_h2_block_id_for_inherited_title(monkeypatch, tmp_path):
    parsed = {
        "a.png": {"topics": [{"title": "General", "tasks": [], "notes": ["# A", "n1"], "questions": []}]},
        "b.png": {"topics": [{"title": "General", "tasks": [], "notes": ["n2"], "questions": []}]},
    }
    p = _make_pipeline(monkeypatch, tmp_path, parsed)

    p.start_batch(ignore_window=False)
    try:
        a = tmp_path / "a.png"
        b = tmp_path / "b.png"
        a.write_bytes(b"x")
        b.write_bytes(b"x")
        _set_mtime(a, 1700000000.0)
        _set_mtime(b, 1700000030.0)
        p.process(a)
        p.process(b)
    finally:
        p.end_batch()

    assert len(p.notion.calls) >= 2
    created_h2_id = "id-1"
    assert p.notion.calls[1]["block_id"] == created_h2_id


def test_watcher_batch_processing_uses_deterministic_sorted_order(monkeypatch, tmp_path):
    watch = tmp_path
    a = watch / "a.png"
    b = watch / "b.png"
    b.write_bytes(b"x")
    a.write_bytes(b"x")

    ts = 1700000000
    a.touch()
    b.touch()
    import os
    os.utime(a, (ts, ts))
    os.utime(b, (ts, ts))

    monkeypatch.setattr(appmod.time, "sleep", lambda _n: None)
    processed = []

    class DummyPipeline:
        def start_batch(self):
            return None

        def end_batch(self):
            return None

        def process(self, path):
            processed.append(path.name)

    handler = appmod.FolderHandler(DummyPipeline(), watch, lambda _msg: None)

    class Event:
        is_directory = False
        src_path = str(b)

    handler.on_created(Event())

    assert processed == ["a.png", "b.png"]
