import json
from pathlib import Path

import menubar_notes_to_notion as appmod


class _FakeResponse:
    model = "gpt-5-mini"
    usage = {"input_tokens": 123, "output_tokens": 45}
    output_text = json.dumps(
        {
            "topics": [
                {
                    "title": "General",
                    "tasks": [{"text": "Ship it", "done": False}],
                    "notes": ["# Team Review", "Discuss rollout"],
                    "questions": ["Any blockers?"],
                }
            ]
        }
    )


class _FakeResponsesAPI:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse()


class _FakeOpenAI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.responses = _FakeResponsesAPI()


class _FakeNotionClient:
    def __init__(self, token: str):
        self.token = token
        self.calls = []
        self._id = 0

    def upload_image_bytes(self, filename, data, content_type="image/jpeg"):
        return "UPLOAD999"

    def find_first_h1_id(self, page_id, page_size=50):
        return "H1BLOCK"

    def list_children_ids(self, block_id, page_size=50):
        return ["FIRSTCHILD"]

    def append_children(self, block_id, children, after_block_id=None):
        self.calls.append((block_id, after_block_id, children))
        results = []
        for c in children:
            self._id += 1
            results.append({"id": f"id-{self._id}", "type": c.get("type")})
        return {"results": results}

    def resolve_parent_page_id(self, block_id):
        return "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"



def test_deterministic_watch_flow_with_fake_clients(monkeypatch, tmp_path: Path):
    watch = tmp_path / "watch"
    watch.mkdir()

    state_path = tmp_path / "processed.json"
    usage_path = tmp_path / "usage.json"

    fake_notion = _FakeNotionClient("token")

    monkeypatch.setattr(appmod, "STATE_PATH", state_path)
    monkeypatch.setattr(appmod, "USAGE_PATH", usage_path)
    monkeypatch.setattr(appmod.time, "sleep", lambda _n: None)
    monkeypatch.setattr(appmod, "image_to_jpeg_bytes", lambda _p: b"jpegbytes")
    monkeypatch.setattr(appmod, "OpenAI", _FakeOpenAI)
    monkeypatch.setattr(appmod, "NotionClient", lambda token: fake_notion)

    notified = {"count": 0}
    monkeypatch.setattr(
        appmod,
        "notify_processed_image",
        lambda *_args, **_kwargs: notified.__setitem__("count", notified["count"] + 1),
    )

    pipeline = appmod.Pipeline(
        openai_key="openai-key",
        model="gpt-5-mini",
        notion_token="notion-token",
        page_id="PAGEID",
        status_cb=lambda _msg: None,
    )
    handler = appmod.FolderHandler(pipeline, watch, lambda _msg: None)

    img = watch / "IMG_5000.png"
    img.write_bytes(b"raw")

    class Event:
        is_directory = False
        src_path = str(img)

    handler.on_created(Event())

    assert (watch / "_processed" / "IMG_5000.png").exists()
    assert not img.exists()

    # heading + container + content append sequence
    assert len(fake_notion.calls) == 3
    assert fake_notion.calls[0][0] == "PAGEID"
    assert fake_notion.calls[0][1] == "H1BLOCK"
    assert fake_notion.calls[1][0] == "PAGEID"
    assert fake_notion.calls[2][0] == "id-2"

    usage = json.loads(usage_path.read_text("utf-8"))
    assert len(usage.get("events", [])) == 1
    assert usage["events"][0]["input_tokens"] == 123
    assert usage["events"][0]["output_tokens"] == 45

    state = json.loads(state_path.read_text("utf-8"))
    assert "last_note_url" in state
    assert state["last_note_url"].startswith("https://www.notion.so/")

    assert notified["count"] == 1
