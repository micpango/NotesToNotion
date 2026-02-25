import json
import os
from datetime import datetime
from pathlib import Path

import notion_format as nf


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


def test_build_notion_blocks_golden_snapshot_complex_case():
    parsed = {
        "topics": [
            {
                "title": "General",
                "tasks": [{"text": "Plan kickoff", "done": False}],
                "notes": [
                    "# Sprint Alpha",
                    "- top bullet",
                    "-- child bullet",
                    "1. numbered item",
                    "1.1 nested numbered",
                    ". open task from note",
                    "x done task from note",
                    "? note question",
                    "# Sprint Beta",
                    "beta plain note",
                ],
                "questions": ["How do we wrap this up?"],
            }
        ]
    }

    blocks = nf.build_notion_blocks(
        parsed=parsed,
        filename="IMG_9999.HEIC",
        image_upload_id="UPLOAD-ABC",
        now=datetime(2026, 2, 25, 12, 34, 0),
        include_entry_heading=True,
        entry_title_override="Overridden Session",
    )

    _assert_matches_golden(
        "notion_blocks_complex.json",
        _normalize(blocks),
    )
