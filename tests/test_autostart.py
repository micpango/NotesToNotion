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
