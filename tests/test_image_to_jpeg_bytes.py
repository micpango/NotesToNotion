import io
from pathlib import Path

from PIL import Image

import menubar_notes_to_notion as appmod


def test_large_image_is_resized_to_max_1800(tmp_path: Path):
    src = tmp_path / "big.png"
    Image.new("RGB", (2400, 1200), color=(10, 20, 30)).save(src, format="PNG")

    out = appmod.image_to_jpeg_bytes(src)
    img = Image.open(io.BytesIO(out))

    assert img.size == (1800, 900)


def test_output_is_jpeg(tmp_path: Path):
    src = tmp_path / "src.png"
    Image.new("RGB", (1000, 1000), color=(1, 2, 3)).save(src, format="PNG")

    out = appmod.image_to_jpeg_bytes(src)
    img = Image.open(io.BytesIO(out))

    assert img.format == "JPEG"


def test_small_image_is_not_resized(tmp_path: Path):
    src = tmp_path / "small.png"
    Image.new("RGB", (1200, 800), color=(100, 120, 140)).save(src, format="PNG")

    out = appmod.image_to_jpeg_bytes(src)
    img = Image.open(io.BytesIO(out))

    assert img.size == (1200, 800)
