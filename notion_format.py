from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional


# Prefixes we may get back from the model even though the content is already categorized.
# We strip these defensively in the formatter so output is clean/deterministic.
_PREFIX_RE = re.compile(r"^\s*([.\-xX\?])\s+")
_NUM_RE = re.compile(r"^\s*(\d+)\.\s+(.*)")


def date_mention_rich_text(dt: datetime):
    iso = dt.astimezone().isoformat(timespec="minutes")
    return [{
        "type": "mention",
        "mention": {"type": "date", "date": {"start": iso}}
    }]


def rt_text(s: str):
    return [{"type": "text", "text": {"content": s}}]


def strip_known_prefix(s: str) -> str:
    """
    Defensive cleanup: remove known handwritten-annotation prefixes if they leak into
    parsed note/question strings.
    Example: "- foo" -> "foo", "? bar" -> "bar"
    """
    s = (s or "").strip()
    s = _PREFIX_RE.sub("", s)
    return s.strip()


def build_notion_blocks(
    parsed: Dict[str, Any],
    filename: str,
    image_upload_id: Optional[str],
    now: datetime,
) -> List[Dict[str, Any]]:
    """
    Pure function: parsed transcription JSON -> Notion blocks.
    No network, no OpenAI, no Notion. Unit-test friendly.
    """
    blocks: List[Dict[str, Any]] = []

    # Entry header (date mention)
    blocks.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": date_mention_rich_text(now) + rt_text(" — Handwritten notes")}
    })

    # Optional image attachment
    if image_upload_id:
        blocks.append({
            "object": "block",
            "type": "image",
            "image": {
                "caption": rt_text(f"Source image: {filename}"),
                "type": "file_upload",
                "file_upload": {"id": image_upload_id},
            }
        })
    else:
        # Only include textual source reference when we could not attach the image
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": rt_text(f"Source: {filename}")}
        })

    blocks.append({"object": "block", "type": "divider", "divider": {}})

    topics = parsed.get("topics") or [{"title": "General", "tasks": [], "notes": [], "questions": []}]

    for t in topics:
        title = (t.get("title") or "General").strip() or "General"
        blocks.append({
            "object": "block",
            "type": "heading_3",
            "heading_3": {"rich_text": rt_text(title)}
        })

        # Tasks -> Notion to_do
        for task in (t.get("tasks") or []):
            text = (task.get("text") or "").strip()
            if not text:
                continue
            blocks.append({
                "object": "block",
                "type": "to_do",
                "to_do": {
                    "rich_text": rt_text(text),
                    "checked": bool(task.get("done", False)),
                }
            })

        # Notes -> numbered list if "1. ..." else bullets
        for note in (t.get("notes") or []):
            note = strip_known_prefix(str(note))
            if not note:
                continue

            m = _NUM_RE.match(note)
            if m:
                text = (m.group(2) or "").strip()
                if text:
                    blocks.append({
                        "object": "block",
                        "type": "numbered_list_item",
                        "numbered_list_item": {"rich_text": rt_text(text)}
                    })
            else:
                blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": rt_text(note)}
                })

        # Questions -> bullet with emoji, but strip leaked prefixes first
        for q in (t.get("questions") or []):
            q = strip_known_prefix(str(q))
            if not q:
                continue
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": rt_text(f"❓ {q}")}
            })


    return blocks