from pathlib import Path
from datetime import datetime

import menubar_notes_to_notion as appmod


def test_pipeline_process_uses_build_notion_blocks(monkeypatch, tmp_path: Path):
    # Arrange: make a fake image file (content doesn't matter because we monkeypatch conversion)
    img = tmp_path / "IMG_TEST.HEIC"
    img.write_bytes(b"fake")

    # Force "not seen" behavior and avoid writing state to user home
    monkeypatch.setattr(appmod.Pipeline, "seen", lambda self, fp: False)
    monkeypatch.setattr(appmod.Pipeline, "mark", lambda self, fp, name: None)

    # Monkeypatch image conversion
    monkeypatch.setattr(appmod, "image_to_jpeg_bytes", lambda p: b"jpegbytes")

    # Monkeypatch transcription (no OpenAI call)
    monkeypatch.setattr(appmod.Pipeline, "transcribe_from_jpeg", lambda self, jpeg, fname: {
        "topics": [{"title": "General", "tasks": [], "notes": [], "questions": ["et spørsmål"]}]
    })

    # Capture calls to build_notion_blocks
    called = {"ok": False, "args": None}

    def fake_build(parsed, filename, image_upload_id, now):
        called["ok"] = True
        called["args"] = (parsed, filename, image_upload_id, now)
        return [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "hi"}}]}}]

    monkeypatch.setattr(appmod, "build_notion_blocks", fake_build)
    notified = {"n": 0, "title": None, "body": None, "url": None}
    monkeypatch.setattr(
        appmod,
        "notify",
        lambda title, body, url, identifier=None: notified.update({"n": notified["n"] + 1, "title": title, "body": body, "url": url}),
    )

    # Fake Notion client to avoid HTTP
    class FakeNotion:
        def upload_image_bytes(self, filename, data, content_type="image/jpeg"):
            return "UPLOAD123"

        def find_first_h1_id(self, page_id, page_size=50):
            return "H1BLOCK"

        def list_children_ids(self, block_id, page_size=50):
            return ["FIRSTCHILD"]

        appended = []

        def append_children(self, block_id, children, after_block_id=None):
            self.appended.append((block_id, children, after_block_id))
            return {
                "results": [
                    {
                        "id": "abcdefab-cdef-abcd-efab-cdefabcdef12",
                        "type": "heading_2",
                    }
                ]
            }

    # Build pipeline but replace notion + openai client usage via monkeypatches above
    p = appmod.Pipeline(
        openai_key="x",
        model="gpt-5.2",
        notion_token="y",
        page_id="PAGEID",
        status_cb=lambda msg: None,
    )
    p.notion = FakeNotion()

    # Act
    p.process(img)

    # Assert: wiring happened
    assert called["ok"] is True
    parsed, filename, image_upload_id, now = called["args"]
    assert filename == "IMG_TEST.HEIC"
    assert image_upload_id == "UPLOAD123"
    assert isinstance(now, datetime)

    # And we appended something to Notion with after="H1BLOCK"
    assert len(p.notion.appended) >= 1
    block_id, children, after = p.notion.appended[0]
    assert block_id == "PAGEID"
    assert after == "H1BLOCK"
    assert notified["n"] == 1
    assert notified["title"] == "Notat lagt til"
    assert notified["body"] != ""
    assert notified["url"] == "https://www.notion.so/abcdefabcdefabcdefabcdefabcdef12"


def test_folder_on_created_triggers_notify_on_success(monkeypatch, tmp_path: Path):
    img = tmp_path / "IMG_WATCH.HEIC"
    img.write_bytes(b"fake")

    monkeypatch.setattr(appmod.Pipeline, "seen", lambda self, fp: False)
    monkeypatch.setattr(appmod.Pipeline, "mark", lambda self, fp, name: None)
    monkeypatch.setattr(appmod, "image_to_jpeg_bytes", lambda p: b"jpegbytes")
    monkeypatch.setattr(
        appmod.Pipeline,
        "transcribe_from_jpeg",
        lambda self, jpeg, fname: {
            "topics": [{"title": "General", "tasks": [], "notes": [], "questions": ["et spørsmål"]}]
        },
    )
    monkeypatch.setattr(
        appmod,
        "build_notion_blocks",
        lambda parsed, filename, image_upload_id, now: [
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": "General"}}]},
            }
        ],
    )
    monkeypatch.setattr(appmod.time, "sleep", lambda _n: None)

    notified = {"n": 0, "title": "", "body": ""}
    monkeypatch.setattr(
        appmod,
        "notify",
        lambda title, body, url, identifier=None: notified.update(
            {"n": notified["n"] + 1, "title": title, "body": body}
        ),
    )

    class FakeNotion:
        def upload_image_bytes(self, filename, data, content_type="image/jpeg"):
            return "UPLOAD999"

        def find_first_h1_id(self, page_id, page_size=50):
            return "H1BLOCK"

        def list_children_ids(self, block_id, page_size=50):
            return ["FIRSTCHILD"]

        def append_children(self, block_id, children, after_block_id=None):
            return {"results": [{"id": "abcdefab-cdef-abcd-efab-cdefabcdef12", "type": "heading_2"}]}

    p = appmod.Pipeline(
        openai_key="x",
        model="gpt-5.2",
        notion_token="y",
        page_id="PAGEID",
        status_cb=lambda msg: None,
    )
    p.notion = FakeNotion()

    handler = appmod.FolderHandler(p, tmp_path, lambda msg: None)

    class Event:
        is_directory = False
        src_path = str(img)

    handler.on_created(Event())

    assert notified["n"] == 1
    assert notified["title"] != ""
    assert notified["body"] != ""


def test_folder_on_created_calls_refresh_menu_cb(monkeypatch, tmp_path: Path):
    img = tmp_path / "IMG_REFRESH.HEIC"
    img.write_bytes(b"fake")
    monkeypatch.setattr(appmod.time, "sleep", lambda _n: None)

    refreshed = {"n": 0}

    class DummyPipeline:
        def process(self, path):
            return None

    handler = appmod.FolderHandler(
        DummyPipeline(),
        tmp_path,
        lambda msg: None,
        refresh_menu_cb=lambda: refreshed.__setitem__("n", refreshed["n"] + 1),
    )

    class Event:
        is_directory = False
        src_path = str(img)

    handler.on_created(Event())
    assert refreshed["n"] == 1
