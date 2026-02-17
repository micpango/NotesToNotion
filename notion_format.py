from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional


# Prefixes we may get back from the model even though the content is already categorized.
# We strip these defensively in the formatter so output is clean/deterministic.
_PREFIX_RE = re.compile(r"^\s*([.\-xX\?])\s+")
_NUM_RE = re.compile(r"^\s*(\d+)\.\s+(.*)")
_HASH_TITLE_RE = re.compile(r"^\s*#\s*(.+)\s*$")


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


def _is_hash_header_line(note_text: str) -> Optional[str]:
    """
    If the note line starts a new entry (e.g. "#Ledermøte" or "# Ledermøte"),
    return the title without '#'. Otherwise return None.
    """
    m = _HASH_TITLE_RE.match(note_text or "")
    if not m:
        return None
    title = (m.group(1) or "").strip()
    return title or None


def _ensure_section(sections: List[Dict[str, Any]], current: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Ensure we have an active section. If none exists, create default.
    Returns active section.
    """
    if current is not None:
        return current
    current = {"title": "Handwritten notes", "topics": []}
    sections.append(current)
    return current


def _get_topic_bucket(section: Dict[str, Any], topic_title: str) -> Dict[str, Any]:
    """
    Return topic bucket within section, creating it if missing.
    Keeps insertion order.
    """
    for t in section["topics"]:
        if t["title"] == topic_title:
            return t
    bucket = {"title": topic_title, "tasks": [], "notes": [], "questions": []}
    section["topics"].append(bucket)
    return bucket


def _section_has_content(section: Dict[str, Any]) -> bool:
    for t in section.get("topics", []):
        if t.get("tasks") or t.get("notes") or t.get("questions"):
            return True
    return False


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

    topics = parsed.get("topics") or [{"title": "General", "tasks": [], "notes": [], "questions": []}]

    # --- NEW: Split into multiple "entries" inside one image based on "#..." note lines.
    sections: List[Dict[str, Any]] = []
    current_section: Optional[Dict[str, Any]] = None

    # Buffer until first "#..." appears (so tasks/questions before first # belong to first section)
    pending_topics: List[Dict[str, Any]] = []

    def _pending_bucket(topic_title: str) -> Dict[str, Any]:
        for b in pending_topics:
            if b["title"] == topic_title:
                return b
        b = {"title": topic_title, "tasks": [], "notes": [], "questions": []}
        pending_topics.append(b)
        return b

    def _flush_pending_into(section: Dict[str, Any]) -> None:
        if not pending_topics:
            return
        section["topics"].extend(pending_topics)
        pending_topics.clear()

    for t in topics:
        topic_title = (t.get("title") or "General").strip() or "General"

        # Tasks
        for task in (t.get("tasks") or []):
            text = (task.get("text") or "").strip()
            if not text:
                continue

            if current_section is None:
                _pending_bucket(topic_title)["tasks"].append(task)
            else:
                _get_topic_bucket(current_section, topic_title)["tasks"].append(task)

        # Notes (may start new section)
        for note in (t.get("notes") or []):
            note_clean = strip_known_prefix(str(note))
            if not note_clean:
                continue

            new_title = _is_hash_header_line(note_clean)
            if new_title:
                # Start new section
                if current_section is None:
                    current_section = {"title": new_title, "topics": []}
                    sections.append(current_section)
                    _flush_pending_into(current_section)
                else:
                    current_section = {"title": new_title, "topics": []}
                    sections.append(current_section)
                continue

            if current_section is None:
                _pending_bucket(topic_title)["notes"].append(note_clean)
            else:
                _get_topic_bucket(current_section, topic_title)["notes"].append(note_clean)

        # Questions
        for q in (t.get("questions") or []):
            q_clean = strip_known_prefix(str(q))
            if not q_clean:
                continue

            if current_section is None:
                _pending_bucket(topic_title)["questions"].append(q_clean)
            else:
                _get_topic_bucket(current_section, topic_title)["questions"].append(q_clean)

    # If we never saw a "#..." section, create default and flush pending into it
    if not sections:
        current_section = {"title": "Handwritten notes", "topics": []}
        sections.append(current_section)
        _flush_pending_into(current_section)

    # Drop empty sections (e.g. "#Foo" then immediately "#Bar" before any content)
    sections = [s for s in sections if _section_has_content(s)]

    # Drop empty sections (e.g. "#Foo" then immediately "#Bar" before any content)
    sections = [s for s in sections if _section_has_content(s)]

    # If nothing survived, fall back to one empty-ish default section
    if not sections:
        sections = [{"title": "Handwritten notes", "topics": []}]

    # --- Render
    for idx, section in enumerate(sections):
        # H2 per section
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": date_mention_rich_text(now) + rt_text(f" — {section['title']}")}
        })

        # Attach image (or Source text) only once, on the first section
        if idx == 0:
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
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": rt_text(f"Source: {filename}")}
                })

        blocks.append({"object": "block", "type": "divider", "divider": {}})

        for t in section.get("topics", []):
            title = t["title"]
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": rt_text(title)}
            })

            # Tasks
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

            # Notes
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

            # Questions
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