from pathlib import Path
import time

import menubar_notes_to_notion as appmod


def test_list_pending_images_filters_and_sorts(tmp_path: Path):
    # Arrange
    # Supported
    a = tmp_path / "a.png"
    b = tmp_path / "b.heic"
    a.write_bytes(b"x")
    b.write_bytes(b"x")

    # Unsupported + hidden
    (tmp_path / "c.txt").write_text("nope")
    (tmp_path / ".hidden.jpg").write_bytes(b"x")

    # Directories should be ignored
    (tmp_path / "_processed").mkdir()
    (tmp_path / "_failed").mkdir()

    # Set mtimes (a older than b)
    now = time.time()
    a_mtime = now - 100
    b_mtime = now - 50
    a.touch()
    b.touch()
    # Force mtimes
    import os
    os.utime(a, (a_mtime, a_mtime))
    os.utime(b, (b_mtime, b_mtime))

    # Act
    pending = appmod.list_pending_images(tmp_path)

    # Assert
    assert [p.name for p in pending] == ["a.png", "b.heic"]
