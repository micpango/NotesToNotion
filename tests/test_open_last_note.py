from pathlib import Path
import copy

import menubar_notes_to_notion as appmod


def test_pipeline_process_persists_last_note_url(monkeypatch, tmp_path: Path):
    img = tmp_path / "IMG_LAST_NOTE.HEIC"
    img.write_bytes(b"fake")

    monkeypatch.setattr(appmod, "state_load", lambda: {"processed": {}})
    saved_states = []
    monkeypatch.setattr(appmod, "state_save", lambda state: saved_states.append(copy.deepcopy(state)))
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
    monkeypatch.setattr(appmod, "notify", lambda title, body, url, identifier=None: None)
    monkeypatch.setattr(appmod.time, "sleep", lambda _n: None)

    class FakeNotion:
        def upload_image_bytes(self, filename, data, content_type="image/jpeg"):
            return "UPLOAD123"

        def find_first_h1_id(self, page_id, page_size=50):
            return "H1BLOCK"

        def list_children_ids(self, block_id, page_size=50):
            return ["FIRSTCHILD"]

        def append_children(self, block_id, children, after_block_id=None):
            return {"results": [{"id": "abcdefab-cdef-abcd-efab-cdefabcdef12", "type": "heading_2"}]}

        def resolve_parent_page_id(self, block_id):
            return "11111111-2222-3333-4444-555555555555"

    p = appmod.Pipeline(
        openai_key="x",
        model="gpt-5.2",
        notion_token="y",
        page_id="PAGEID",
        status_cb=lambda msg: None,
    )
    p.notion = FakeNotion()

    p.process(img)

    assert saved_states
    out = saved_states[-1]
    assert out["last_note_url"] == "https://www.notion.so/11111111222233334444555555555555#abcdefabcdefabcdefabcdefabcdef12"
    assert out["last_note_title"] == "General"
    assert "last_note_ts" in out


def test_open_last_note_opens_url(monkeypatch):
    opened = {"cmd": None}
    alerted = {"n": 0}
    url = "https://www.notion.so/abcdefabcdefabcdefabcdefabcdef12"

    monkeypatch.setattr(appmod, "state_load", lambda: {"last_note_url": url})
    monkeypatch.setattr(appmod.subprocess, "run", lambda cmd: opened.__setitem__("cmd", cmd))
    monkeypatch.setattr(appmod.rumps, "alert", lambda *args: alerted.__setitem__("n", alerted["n"] + 1))

    app = appmod.NotesMenuApp.__new__(appmod.NotesMenuApp)
    app.open_last_note(None)

    assert opened["cmd"] == ["open", url]
    assert alerted["n"] == 0


def test_open_last_note_alerts_when_missing(monkeypatch):
    opened = {"n": 0}
    alerted = {"args": None}

    monkeypatch.setattr(appmod, "state_load", lambda: {"processed": {}})
    monkeypatch.setattr(appmod.subprocess, "run", lambda cmd: opened.__setitem__("n", opened["n"] + 1))
    monkeypatch.setattr(appmod.rumps, "alert", lambda *args: alerted.__setitem__("args", args))

    app = appmod.NotesMenuApp.__new__(appmod.NotesMenuApp)
    app.open_last_note(None)

    assert opened["n"] == 0
    assert alerted["args"] == ("No note yet", "No processed note in this session")
