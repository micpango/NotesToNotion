import menubar_notes_to_notion as appmod


def test_build_notion_block_url_strips_dashes():
    block_id = "abcdefab-cdef-abcd-efab-cdefabcdef12"
    url = appmod.build_notion_block_url(block_id)
    assert url == "https://www.notion.so/abcdefabcdefabcdefabcdefabcdef12"


def test_build_notion_page_anchor_url_strips_dashes():
    page_id = "11111111-2222-3333-4444-555555555555"
    block_id = "abcdefab-cdef-abcd-efab-cdefabcdef12"
    url = appmod.build_notion_page_anchor_url(page_id, block_id)
    assert url == "https://www.notion.so/11111111222233334444555555555555#abcdefabcdefabcdefabcdefabcdef12"


def test_extract_first_h2_block_id_from_append_response_prefers_h2_id():
    resp = {
        "results": [
            {"id": "x", "type": "paragraph"},
            {"id": "h2id", "type": "heading_2"},
        ]
    }
    out = appmod.extract_first_h2_block_id_from_append_response(resp)
    assert out == "h2id"


def test_extract_first_h2_block_id_from_append_response_falls_back_to_first_result():
    resp = {
        "results": [
            {"id": "abcdefab-cdef-abcd-efab-cdefabcdef12", "type": "paragraph"},
        ]
    }
    out = appmod.extract_first_h2_block_id_from_append_response(resp)
    assert out == "abcdefab-cdef-abcd-efab-cdefabcdef12"


def test_notify_processed_image_triggers_notification_with_url(monkeypatch):
    called = {"args": None}
    monkeypatch.setattr(
        appmod,
        "notify",
        lambda title, body, url, identifier=None: called.__setitem__("args", (title, body, url)),
    )

    appmod.notify_processed_image(
        section_title="Ledermøte",
        filename="IMG_1000.HEIC",
        url="https://www.notion.so/some-page#some-block",
    )

    assert called["args"] == (
        "Notat lagt til",
        "Ledermøte",
        "https://www.notion.so/some-page#some-block",
    )


def test_notify_processed_image_uses_generic_text_when_no_custom_title(monkeypatch):
    called = {"args": None}
    monkeypatch.setattr(
        appmod,
        "notify",
        lambda title, body, url, identifier=None: called.__setitem__("args", (title, body, url)),
    )

    appmod.notify_processed_image(
        section_title="Handwritten notes",
        filename="IMG_1001.HEIC",
        url="https://www.notion.so/some-page#some-block",
    )

    assert called["args"] == (
        "Notat lagt til",
        "IMG_1001.HEIC",
        "https://www.notion.so/some-page#some-block",
    )


def test_notify_sets_user_info_url_and_delivers_notification(monkeypatch):
    called = {
        "title": None,
        "body": None,
        "sound": "unset",
        "identifier": None,
        "user_info": None,
        "delivered": None,
    }

    class DummyNote:
        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            return self

        def setTitle_(self, title):
            called["title"] = title

        def setInformativeText_(self, body):
            called["body"] = body

        def setSoundName_(self, sound):
            called["sound"] = sound

        def setIdentifier_(self, identifier):
            called["identifier"] = identifier

        def setUserInfo_(self, user_info):
            called["user_info"] = user_info

    class DummyCenterObj:
        def setDelegate_(self, delegate):
            called["delegate"] = delegate

        def deliverNotification_(self, note):
            called["delivered"] = note

    center_obj = DummyCenterObj()

    class DummyCenterClass:
        @classmethod
        def defaultUserNotificationCenter(cls):
            return center_obj

    monkeypatch.setattr(appmod, "NSUserNotificationCenter", DummyCenterClass)
    monkeypatch.setattr(appmod, "NSUserNotification", DummyNote)
    monkeypatch.setattr(appmod, "ensure_notification_center_delegate", lambda: None)

    appmod.notify("NotesToNotion", "Notat lagt til", "https://www.notion.so/some-page#some-block")

    assert called["title"] == "NotesToNotion"
    assert called["body"] == "Notat lagt til"
    assert called["sound"] is None
    assert called["identifier"].startswith("note-")
    assert called["user_info"] == {"url": "https://www.notion.so/some-page#some-block"}
    assert called["delivered"] is not None


def test_notify_processed_image_generates_unique_identifiers(monkeypatch):
    called = []
    monkeypatch.setattr(
        appmod,
        "notify",
        lambda title, body, url, identifier=None: called.append((title, body, url, identifier)),
    )

    appmod.notify_processed_image(
        section_title="Ledermøte",
        filename="IMG_2000.HEIC",
        url="https://www.notion.so/some-page#some-block",
    )
    appmod.notify_processed_image(
        section_title="Ledermøte",
        filename="IMG_2000.HEIC",
        url="https://www.notion.so/some-page#some-block",
    )

    assert len(called) == 2
    assert called[0][3] != called[1][3]


def test_notification_delegate_click_opens_url(monkeypatch):
    called = {"cmd": None}
    monkeypatch.setattr(appmod.subprocess, "run", lambda cmd: called.__setitem__("cmd", cmd))

    class DummyNotification:
        def userInfo(self):
            return {"url": "https://www.notion.so/some-page#some-block"}

    delegate = appmod.NotificationCenterDelegate()
    delegate.userNotificationCenter_didActivateNotification_(None, DummyNotification())

    assert called["cmd"] == ["open", "https://www.notion.so/some-page#some-block"]

def test_dispatch_processed_image_notification_uses_timer_off_main_thread(monkeypatch):
    called = {"timer_started": False, "interval": None, "notified": 0}

    class DummyTimer:
        def __init__(self, callback, interval):
            self.callback = callback
            called["interval"] = interval

        def start(self):
            called["timer_started"] = True
            self.callback(None)

    class DummyThread:
        name = "Thread-1"

    monkeypatch.setattr(appmod.rumps, "Timer", DummyTimer)
    monkeypatch.setattr(appmod.threading, "current_thread", lambda: DummyThread())
    monkeypatch.setattr(
        appmod,
        "notify_processed_image",
        lambda section_title, filename, url: called.__setitem__("notified", called["notified"] + 1),
    )

    appmod.dispatch_processed_image_notification(
        section_title="Ledermøte",
        filename="IMG_1002.HEIC",
        url="https://www.notion.so/some-page#some-block",
    )

    assert called["timer_started"] is True
    assert called["interval"] == 0
    assert called["notified"] == 1


def test_failure_notification_sent_once_on_folder_exception(monkeypatch, tmp_path):
    img = tmp_path / "IMG_FAIL.HEIC"
    img.write_bytes(b"x")
    monkeypatch.setattr(appmod.time, "sleep", lambda _n: None)

    called = {"n": 0, "path": None, "exc": None}

    def _notify_failed(path, exc):
        called["n"] += 1
        called["path"] = path
        called["exc"] = exc

    monkeypatch.setattr(appmod, "notify_failed_image", _notify_failed)

    class FailingPipeline:
        def process(self, path):
            raise RuntimeError("Feilet her\nDetaljer")

    handler = appmod.FolderHandler(FailingPipeline(), tmp_path, lambda _msg: None)

    class Event:
        is_directory = False
        src_path = str(img)

    handler.on_created(Event())

    assert called["n"] == 1
    assert called["path"] == img
    assert "Feilet her" in str(called["exc"])


def test_failure_notification_not_duplicated_for_same_file(monkeypatch, tmp_path):
    monkeypatch.setattr(appmod, "_failed_notification_paths", set())
    called = {"n": 0}
    monkeypatch.setattr(
        appmod,
        "notify",
        lambda title, body, url, identifier=None: called.__setitem__("n", called["n"] + 1),
    )

    path = tmp_path / "IMG_DUP.HEIC"
    appmod.notify_failed_image(path, RuntimeError("A"))
    appmod.notify_failed_image(path, RuntimeError("B"))

    assert called["n"] == 1


def test_failure_notification_body_trimmed_and_uses_first_line(monkeypatch, tmp_path):
    monkeypatch.setattr(appmod, "_failed_notification_paths", set())
    called = {"title": None, "body": None}

    monkeypatch.setattr(
        appmod,
        "notify",
        lambda title, body, url, identifier=None: called.update({"title": title, "body": body}),
    )

    long_first_line = "Dette er en veldig lang feilmelding " * 8
    exc = RuntimeError(long_first_line + "\nAndre linje skal ikke med")
    path = tmp_path / "IMG_LONG_ERROR.HEIC"

    appmod.notify_failed_image(path, exc)

    assert called["title"] == "Notat feilet"
    assert called["body"].startswith("IMG_LONG_ERROR.HEIC — ")
    assert "\n" not in called["body"]
    assert "Andre linje" not in called["body"]
    assert len(called["body"]) <= 120
