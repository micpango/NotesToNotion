import json
import os
from pathlib import Path

import menubar_notes_to_notion as appmod


GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


def _normalize(value):
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == "date" and isinstance(v, dict) and "start" in v:
                cloned = dict(v)
                cloned["start"] = "<DATE_MENTION>"
                out[k] = _normalize(cloned)
            else:
                out[k] = _normalize(v)
        return out
    return value


def _assert_matches_golden(name: str, payload) -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    path = GOLDEN_DIR / name
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    if os.getenv("UPDATE_GOLDEN") == "1":
        path.write_text(rendered, "utf-8")

    assert path.exists(), f"Missing golden snapshot: {path}"
    assert path.read_text("utf-8") == rendered


class _FakeNotion:
    def __init__(self):
        self.calls = []
        self._id = 0

    def upload_image_bytes(self, filename, data, content_type="image/jpeg"):
        return "UPLOAD123"

    def find_first_h1_id(self, page_id, page_size=50):
        return "H1BLOCK"

    def list_children_ids(self, block_id, page_size=50):
        return ["FIRSTCHILD"]

    def append_children(self, block_id, children, after_block_id=None):
        self.calls.append(
            {
                "block_id": block_id,
                "after_block_id": after_block_id,
                "children": children,
            }
        )
        results = []
        for child in children:
            self._id += 1
            item = {"id": f"id-{self._id}"}
            if child.get("type"):
                item["type"] = child.get("type")
            results.append(item)
        return {"results": results}

    def resolve_parent_page_id(self, block_id):
        return "11111111-2222-3333-4444-555555555555"



def test_pipeline_append_sequence_matches_golden(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(appmod, "USAGE_PATH", tmp_path / "usage.json")
    monkeypatch.setattr(appmod, "STATE_PATH", tmp_path / "processed.json")
    monkeypatch.setattr(appmod.time, "sleep", lambda _n: None)
    monkeypatch.setattr(appmod, "image_to_jpeg_bytes", lambda _p: b"jpeg")
    monkeypatch.setattr(appmod, "notify_processed_image", lambda *args, **kwargs: None)
    monkeypatch.setattr(appmod.Pipeline, "record_usage", lambda self, filename: None)
    monkeypatch.setattr(appmod.Pipeline, "seen", lambda self, fp: False)
    monkeypatch.setattr(appmod.Pipeline, "mark", lambda self, fp, name: None)

    parsed_by_name = {
        "a.png": {
            "topics": [
                {
                    "title": "General",
                    "tasks": [],
                    "notes": ["# Team Sync", "first note"],
                    "questions": [],
                }
            ]
        },
        "b.png": {
            "topics": [
                {
                    "title": "General",
                    "tasks": [],
                    "notes": ["second note"],
                    "questions": [],
                }
            ]
        },
    }

    monkeypatch.setattr(
        appmod.Pipeline,
        "transcribe_from_jpeg",
        lambda self, jpeg, filename: parsed_by_name[filename],
    )

    pipeline = appmod.Pipeline(
        openai_key="x",
        model="gpt-5-mini",
        notion_token="y",
        page_id="PAGEID",
        status_cb=lambda _msg: None,
    )
    pipeline.notion = _FakeNotion()

    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    a.write_bytes(b"x")
    b.write_bytes(b"x")

    import os

    os.utime(a, (1700000000.0, 1700000000.0))
    os.utime(b, (1700000030.0, 1700000030.0))

    pipeline.start_batch(ignore_window=False)
    try:
        pipeline.process(a)
        pipeline.process(b)
    finally:
        pipeline.end_batch()

    _assert_matches_golden(
        "pipeline_append_sequence.json",
        _normalize(pipeline.notion.calls),
    )
