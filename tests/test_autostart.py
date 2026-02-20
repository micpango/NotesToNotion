import menubar_notes_to_notion as appmod


def _patch_rumps_headless(monkeypatch):
    # Prevent touching macOS GUI and still satisfy rumps internals that NotesMenuApp relies on.

    # Fake base init
    monkeypatch.setattr(appmod.rumps.App, "__init__", lambda self, *a, **k: None)
    monkeypatch.setattr(appmod, "notify", lambda *a, **k: None)

    # Minimal MenuItem
    class DummyMenuItem:
        def __init__(self, title, callback=None):
            self.title = title
            self.callback = callback
            self.state = 0

    monkeypatch.setattr(appmod.rumps, "MenuItem", DummyMenuItem)

    # Dummy menu backing store used by rumps' menu property setter: self._menu.update(iterable)
    class DummyMenu:
        def update(self, iterable):
            # rumps passes list-like items; we don't need to store them for this test
            self.items = list(iterable)

    # Ensure every NotesMenuApp instance has _menu before NotesMenuApp.__init__ assigns self.menu = [...]
    orig_init = appmod.NotesMenuApp.__init__

    def wrapped_init(self, *a, **k):
        self._menu = DummyMenu()
        return orig_init(self, *a, **k)

    monkeypatch.setattr(appmod.NotesMenuApp, "__init__", wrapped_init)


def test_autostart_schedules_timer_when_config_present(monkeypatch):
    _patch_rumps_headless(monkeypatch)

    created = {"timer": None, "started": False}

    class DummyTimer:
        def __init__(self, callback, interval):
            created["timer"] = {"callback": callback, "interval": interval}
        def start(self):
            created["started"] = True

    monkeypatch.setattr(appmod.rumps, "Timer", DummyTimer)

    # Make config present so autostart triggers
    monkeypatch.setattr(appmod.NotesMenuApp, "_ensure_config", lambda self: {"WATCH_FOLDER": "/tmp"})

    # Avoid side effects in tests
    monkeypatch.setattr(appmod, "log", lambda msg: None)

    # Act
    app = appmod.NotesMenuApp()

    # Assert
    assert created["timer"] is not None
    assert created["timer"]["interval"] == 1
    assert created["timer"]["callback"].__self__ is app
    assert created["timer"]["callback"].__name__ == "_autostart_watch"
    assert created["started"] is True


def test_autostart_not_scheduled_when_config_missing(monkeypatch):
    _patch_rumps_headless(monkeypatch)

    created = {"timer_created": False}

    class DummyTimer:
        def __init__(self, callback, interval):
            created["timer_created"] = True
        def start(self):
            pass

    monkeypatch.setattr(appmod.rumps, "Timer", DummyTimer)

    monkeypatch.setattr(appmod.NotesMenuApp, "_ensure_config", lambda self: None)
    monkeypatch.setattr(appmod, "log", lambda msg: None)

    # Act
    _ = appmod.NotesMenuApp()

    # Assert
    assert created["timer_created"] is False


def test_open_watch_folder_label_shows_failed_count(monkeypatch, tmp_path):
    _patch_rumps_headless(monkeypatch)

    watch = tmp_path / "watch"
    failed = watch / "_failed"
    failed.mkdir(parents=True)
    (failed / "a.jpg").write_bytes(b"x")
    (failed / "b.jpg").write_bytes(b"x")
    (failed / "c.jpg").write_bytes(b"x")

    monkeypatch.setattr(appmod, "load_config", lambda: {"WATCH_FOLDER": str(watch)})
    monkeypatch.setattr(appmod.NotesMenuApp, "_ensure_config", lambda self: None)
    monkeypatch.setattr(appmod, "log", lambda msg: None)

    app = appmod.NotesMenuApp()

    assert "3 failed" in app.mi_open_watch.title


def test_open_watch_folder_label_hides_failed_when_zero(monkeypatch, tmp_path):
    _patch_rumps_headless(monkeypatch)

    watch = tmp_path / "watch"
    watch.mkdir(parents=True)

    monkeypatch.setattr(appmod, "load_config", lambda: {"WATCH_FOLDER": str(watch)})
    monkeypatch.setattr(appmod.NotesMenuApp, "_ensure_config", lambda self: None)
    monkeypatch.setattr(appmod, "log", lambda msg: None)

    app = appmod.NotesMenuApp()

    assert app.mi_open_watch.title == "Open Watch Folder"


def test_open_watch_folder_label_ignores_hidden_files(monkeypatch, tmp_path):
    _patch_rumps_headless(monkeypatch)

    watch = tmp_path / "watch"
    failed = watch / "_failed"
    failed.mkdir(parents=True)
    (failed / ".DS_Store").write_bytes(b"x")

    monkeypatch.setattr(appmod, "load_config", lambda: {"WATCH_FOLDER": str(watch)})
    monkeypatch.setattr(appmod.NotesMenuApp, "_ensure_config", lambda self: None)
    monkeypatch.setattr(appmod, "log", lambda msg: None)

    app = appmod.NotesMenuApp()

    assert app.mi_open_watch.title == "Open Watch Folder"


def test_open_watch_folder_refreshes_label_before_open(monkeypatch, tmp_path):
    _patch_rumps_headless(monkeypatch)

    watch = tmp_path / "watch"
    failed = watch / "_failed"
    failed.mkdir(parents=True)

    monkeypatch.setattr(appmod, "load_config", lambda: {"WATCH_FOLDER": str(watch)})
    monkeypatch.setattr(appmod.NotesMenuApp, "_ensure_config", lambda self: None)
    monkeypatch.setattr(appmod, "log", lambda msg: None)

    opened = {"cmd": None}
    monkeypatch.setattr(appmod.subprocess, "run", lambda cmd: opened.__setitem__("cmd", cmd))

    app = appmod.NotesMenuApp()
    assert app.mi_open_watch.title == "Open Watch Folder"

    (failed / "a.jpg").write_bytes(b"x")
    app.open_watch_folder(None)

    assert opened["cmd"] == ["open", str(watch)]
    assert "1 failed" in app.mi_open_watch.title


def test_menu_no_longer_contains_open_failed(monkeypatch):
    _patch_rumps_headless(monkeypatch)

    monkeypatch.setattr(appmod, "load_config", lambda: {})
    monkeypatch.setattr(appmod.NotesMenuApp, "_ensure_config", lambda self: None)
    monkeypatch.setattr(appmod, "log", lambda msg: None)

    app = appmod.NotesMenuApp()
    titles = [item.title for item in getattr(app._menu, "items", []) if hasattr(item, "title")]
    assert "Open _failed" not in titles


def test_start_watching_uses_default_openai_model(monkeypatch, tmp_path):
    _patch_rumps_headless(monkeypatch)

    watch = tmp_path / "watch"
    cfg = {
        "WATCH_FOLDER": str(watch),
        "NOTION_PAGE_ID": "PAGEID",
        "OPENAI_MODEL": "gpt-5.2",
    }

    monkeypatch.setattr(appmod, "load_config", lambda: cfg)
    monkeypatch.setattr(appmod.NotesMenuApp, "_ensure_config", lambda self: cfg)
    monkeypatch.setattr(appmod, "keychain_get", lambda name: "token")
    monkeypatch.setattr(appmod, "log", lambda msg: None)
    monkeypatch.setattr(appmod.rumps, "alert", lambda *args: None)
    monkeypatch.setattr(appmod, "list_pending_images", lambda watch_path: [])

    used = {"model": None}

    class DummyPipeline:
        def __init__(self, openai_key, model, notion_token, page_id, status_cb):
            used["model"] = model

    class DummyFolderHandler:
        def __init__(self, pipeline, watch, status_cb, refresh_menu_cb=None):
            pass

    class DummyObserver:
        def schedule(self, handler, path, recursive=False):
            return None

        def start(self):
            return None

    monkeypatch.setattr(appmod, "Pipeline", DummyPipeline)
    monkeypatch.setattr(appmod, "FolderHandler", DummyFolderHandler)
    monkeypatch.setattr(appmod, "Observer", lambda: DummyObserver())

    app = appmod.NotesMenuApp()
    app.start_watching(None)

    assert used["model"] == appmod.DEFAULT_OPENAI_MODEL
