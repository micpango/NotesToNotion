from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional


# Prefixes we may get back from the model even though the content is already categorized.
# We strip these defensively in the formatter so output is clean/deterministic.
_PREFIX_RE = re.compile(r"^\s*([.\-xX\?])\s+")
_NUM_RE = re.compile(r"^\s*(\d+)\.\s+(.*)")
_HASH_TITLE_RE = re.compile(r"^\s*#\s*(.+)\s*$")
_BULLET_TASK_PREFIXES = ("•", "·", "∙", "◦", "○")


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


def _is_hash_header_line(line: str) -> Optional[str]:
    """
    If the line starts a new entry (e.g. "#Ledermøte" or "# Ledermøte"),
    return the title without '#'. Otherwise return None.
    """
    m = _HASH_TITLE_RE.match(line or "")
    if not m:
        return None
    title = (m.group(1) or "").strip()
    return title or None


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


def _split_prefix_kind(raw_line: str) -> tuple[str, str]:
    """
    Returns (kind, text) where kind in:
      - "hash" (start new section)
      - "task_open"
      - "task_done"
      - "question"
      - "note"
    """
    s = (raw_line or "").strip()
    if not s:
        return ("note", "")

    # hash section marker must win, even if someone wrote "- #Ledermøte"
    # so check after stripping known prefixes once for detection only
    s_for_hash = strip_known_prefix(s)
    h = _is_hash_header_line(s_for_hash)
    if h:
        return ("hash", h)

    # detect explicit prefixes on the ORIGINAL trimmed string
    # (we also accept variants without trailing space defensively)
    if s.startswith(". "):
        return ("task_open", s[2:].strip())
    if s.startswith("."):
        return ("task_open", s[1:].strip())

    if s.lower().startswith("x "):
        return ("task_done", s[2:].strip())
    if s.lower().startswith("x"):
        return ("task_done", s[1:].strip())

    if s.startswith("? "):
        q = s[2:].strip()
        # if question accidentally includes numbering, strip it
        m = _NUM_RE.match(q)
        if m:
            q = (m.group(2) or "").strip()
        return ("question", q)

    if s.startswith("?"):
        q = s[1:].strip()
        m = _NUM_RE.match(q)
        if m:
            q = (m.group(2) or "").strip()
        return ("question", q)

    if s.startswith("- "):
        return ("note", s[2:].strip())
    if s.startswith("-"):
        return ("note", s[1:].strip())

    # Handwritten "dot" often becomes a bullet character in transcription.
    # In your notation, dot-at-start means task.
    if s and s[0] in _BULLET_TASK_PREFIXES:
        text = s[1:].strip()
        return ("task_open", text)

    # default note
    return ("note", s)


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

    # Split into multiple "entries" inside one image based on "#..." lines inside notes.
    sections: List[Dict[str, Any]] = []
    current_section: Optional[Dict[str, Any]] = None

    # Buffer until first # appears
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

    def _ensure_section(title: str) -> Dict[str, Any]:
        nonlocal current_section
        current_section = {"title": title, "topics": []}
        sections.append(current_section)
        return current_section

    # ---- Normalize / route content
    for t in topics:
        topic_title = (t.get("title") or "General").strip() or "General"

        # 1) Tasks from model (trusted bucket)
        for task in (t.get("tasks") or []):
            text = (task.get("text") or "").strip()
            if not text:
                continue
            if current_section is None:
                _pending_bucket(topic_title)["tasks"].append(task)
            else:
                _get_topic_bucket(current_section, topic_title)["tasks"].append(task)

        # 2) Questions from model (trusted bucket)
        for q in (t.get("questions") or []):
            q_clean = strip_known_prefix(str(q))
            if not q_clean:
                continue
            if current_section is None:
                _pending_bucket(topic_title)["questions"].append(q_clean)
            else:
                _get_topic_bucket(current_section, topic_title)["questions"].append(q_clean)

        # 3) Notes may contain inline routing markers (# …) or leaked prefixes (. / ? / x / -)
        for raw_note in (t.get("notes") or []):
            kind, text = _split_prefix_kind(str(raw_note))
            if kind == "hash":
                # Start new section; flush pending into first section
                if current_section is None:
                    sec = _ensure_section(text)
                    _flush_pending_into(sec)
                else:
                    _ensure_section(text)
                continue

            if not text:
                continue

            # choose bucket (pending or current)
            if current_section is None:
                bucket = _pending_bucket(topic_title)
            else:
                bucket = _get_topic_bucket(current_section, topic_title)

            if kind == "task_open":
                bucket["tasks"].append({"text": text, "done": False})
            elif kind == "task_done":
                bucket["tasks"].append({"text": text, "done": True})
            elif kind == "question":
                bucket["questions"].append(text)
            else:
                # note
                bucket["notes"].append(text)

    # If we never saw a "#..." section, create default and flush pending into it
    if not sections:
        sec = {"title": "Handwritten notes", "topics": []}
        sections.append(sec)
        _flush_pending_into(sec)

    # Drop empty sections (e.g. "#Foo" then immediately "#Bar")
    sections = [s for s in sections if _section_has_content(s)]
    if not sections:
        sections = [{"title": "Handwritten notes", "topics": []}]

    # ---- Render
    for idx, section in enumerate(sections):
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

            # Notes: numbered list if "1. ..." else bullets
            for note in (t.get("notes") or []):
                note = (note or "").strip()
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
                q = (q or "").strip()
                if not q:
                    continue
                blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": rt_text(f"❓ {q}")}
                })

    return blocks