# prompt_contract.py

PROMPT = r"""
You are transcribing handwritten notes from an image into structured data.

Rules:
- Underlined text = topic / agenda point

Line prefixes (must be first character on the line):
- "# " (hash + space) = start of a NEW entry (meeting/session marker).
  IMPORTANT:
  - Preserve the entire line INCLUDING the leading "#" exactly as written.
  - Include these "# ..." lines in the output as note strings (in "notes").
  - Do NOT remove or rewrite the "#".
  - A single image can contain multiple "# ..." lines; each one marks the start of a new entry.
- ". " (dot + space) = task (done=false)
- "x " (x + space) = completed task (done=true)
- "- " (dash + space) = note
- "? " (question mark + space) = question

Numbered lines:
- "1. " / "2. " / "3. " ... at the start of a line = numbered note item.
  Keep the number prefix in the text (e.g. "1. ") so it can be rendered as a numbered list.

Other:
- no prefix = note
Group items under the most recent topic; if none, topic is "General".
Do not invent content. If unreadable, omit it.

Output ONLY valid JSON:
{
  "topics": [
    {
      "title": "Topic name",
      "tasks": [{"text":"...", "done": false}],
      "notes": ["..."],
      "questions": ["..."]
    }
  ]
}
""".strip()