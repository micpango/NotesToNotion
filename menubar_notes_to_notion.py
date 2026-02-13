import io
import json
import os
import re
import time
import threading
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional

import rumps
import keyring
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from openai import OpenAI

from PIL import Image
import pillow_heif
pillow_heif.register_heif_opener()

APP_NAME = "NotesToNotion"
SERVICE_NAME = "com.notes-to-notion"

CONFIG_DIR = Path.home() / "Library" / "Application Support" / "NotesToNotion"
CONFIG_PATH = CONFIG_DIR / "config.json"
STATE_PATH = CONFIG_DIR / "processed.json"

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
NOTION_VERSION = "2025-09-03"

PROMPT = r"""
You are transcribing handwritten notes from an image into structured data.

Rules:
- Underlined text = topic / agenda point
- "." at start = task (done=false)
- "x" at start = completed task (done=true)
- "-" at start = note
- "?" at start = question
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


def now_dt():
    return datetime.now()


def date_mention_rich_text(dt: datetime):
    iso = dt.astimezone().isoformat(timespec="minutes")
    return [{
        "type": "mention",
        "mention": {
            "type": "date",
            "date": {"start": iso}
        }
    }]


def rt_text(s: str):
    return [{"type": "text", "text": {"content": s}}]


def load_config():
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text("utf-8"))


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def state_load():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text("utf-8"))
    return {"processed": {}}


def state_save(state):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def keychain_set(name, value):
    keyring.set_password(SERVICE_NAME, name, value)


def keychain_get(name):
    return keyring.get_password(SERVICE_NAME, name)


def extract_notion_page_id(input_str: str) -> str:
    s = input_str.strip().split("?")[0]
    m = re.search(r"([0-9a-fA-F]{32})", s.replace("-", ""))
    if not m:
        raise ValueError("Invalid Notion page URL.")
    raw = m.group(1).lower()
    return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"


def image_to_jpeg_bytes(path: Path) -> bytes:
    img = Image.open(path)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def jpeg_to_data_url(b: bytes) -> str:
    import base64
    return "data:image/jpeg;base64," + base64.b64encode(b).decode()


class NotionClient:
    def __init__(self, token: str):
        self.token = token
        self.base = "https://api.notion.com/v1"

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def append(self, block_id, children):
        url = f"{self.base}/blocks/{block_id}/children"
        r = requests.patch(url, headers=self._headers(), data=json.dumps({"children": children}))
        if r.status_code >= 300:
            raise RuntimeError(r.text)


class Pipeline:
    def __init__(self, openai_key, model, notion_token, page_id, status_cb):
        self.client = OpenAI(api_key=openai_key)
        self.model = model
        self.notion = NotionClient(notion_token)
        self.page_id = page_id
        self.status_cb = status_cb
        self.state = state_load()

    def fingerprint(self, path: Path):
        import hashlib
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def seen(self, fp):
        return fp in self.state["processed"]

    def mark(self, fp, name):
        self.state["processed"][fp] = {"name": name, "ts": time.time()}
        state_save(self.state)

    def transcribe(self, path: Path):
        jpeg = image_to_jpeg_bytes(path)
        data_url = jpeg_to_data_url(jpeg)

        resp = self.client.responses.create(
            model=self.model,
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": PROMPT},
                    {"type": "input_image", "image_url": data_url},
                ]
            }]
        )
        out = resp.output_text().strip()
        start = out.find("{")
        end = out.rfind("}")
        return json.loads(out[start:end+1])

    def notion_blocks(self, parsed, filename):
        blocks = []
        dt = now_dt()

        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": date_mention_rich_text(dt) + rt_text(" — Handwritten notes")
            }
        })

        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": rt_text(f"Source: {filename}")}
        })

        blocks.append({"object": "block", "type": "divider", "divider": {}})

        topics = parsed.get("topics") or [{"title":"General","tasks":[],"notes":[],"questions":[]}]
        for t in topics:
            title = (t.get("title") or "General").strip()

            blocks.append({
                "object":"block",
                "type":"heading_3",
                "heading_3":{"rich_text":rt_text(title)}
            })

            for task in t.get("tasks", []):
                text = task.get("text", "").strip()
                if text:
                    blocks.append({
                        "object":"block",
                        "type":"to_do",
                        "to_do":{
                            "rich_text":rt_text(text),
                            "checked":bool(task.get("done", False))
                        }
                    })

            for note in t.get("notes", []):
                blocks.append({
                    "object":"block",
                    "type":"bulleted_list_item",
                    "bulleted_list_item":{"rich_text":rt_text(note)}
                })

            for q in t.get("questions", []):
                blocks.append({
                    "object":"block",
                    "type":"toggle",
                    "toggle":{"rich_text":rt_text(f"Q: {q}")}}
                )

        return blocks

    def process(self, path: Path):
        fp = self.fingerprint(path)
        if self.seen(fp):
            return

        parsed = self.transcribe(path)
        blocks = self.notion_blocks(parsed, path.name)

        chunk = 80
        for i in range(0, len(blocks), chunk):
            self.notion.append(self.page_id, blocks[i:i+chunk])
            time.sleep(0.1)

        self.mark(fp, path.name)


class FolderHandler(FileSystemEventHandler):
    def __init__(self, pipeline: Pipeline, watch: Path):
        self.pipeline = pipeline
        self.watch = watch
        self.proc = watch / "_processed"
        self.fail = watch / "_failed"
        self.proc.mkdir(exist_ok=True)
        self.fail.mkdir(exist_ok=True)

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() not in SUPPORTED_EXTS:
            return
        try:
            self.pipeline.process(path)
            path.replace(self.proc / path.name)
        except Exception:
            path.replace(self.fail / path.name)


class NotesMenuApp(rumps.App):
    def __init__(self):
        super().__init__(APP_NAME)
        self.title = "📷📝"
        self.observer = None
        self.menu = [
            "Start Watching",
            "Stop Watching",
            None,
            "Setup…",
            "Quit"
        ]

    def start_watching(self, _):
        cfg = load_config()
        watch = Path(cfg["WATCH_FOLDER"]).expanduser()
        watch.mkdir(parents=True, exist_ok=True)

        pipeline = Pipeline(
            keychain_get("OPENAI_API_KEY"),
            "gpt-5.2",
            keychain_get("NOTION_TOKEN"),
            cfg["NOTION_PAGE_ID"],
            lambda x: print(x)
        )

        handler = FolderHandler(pipeline, watch)
        self.observer = Observer()
        self.observer.schedule(handler, str(watch), recursive=False)
        self.observer.start()

    def stop_watching(self, _):
        if self.observer:
            self.observer.stop()

    def setup(self, _):
        w = rumps.Window("Watch folder path").run()
        n = rumps.Window("Notion page URL").run()
        notion_tok = rumps.Window("Notion token").run()
        openai = rumps.Window("OpenAI key").run()

        cfg = {
            "WATCH_FOLDER": w.text.strip(),
            "NOTION_PAGE_ID": extract_notion_page_id(n.text)
        }
        save_config(cfg)
        keychain_set("NOTION_TOKEN", notion_tok.text.strip())
        keychain_set("OPENAI_API_KEY", openai.text.strip())

    def quit(self, _):
        rumps.quit_application()
