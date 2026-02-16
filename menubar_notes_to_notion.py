# ------------------------------
# NotesToNotion v0.2.1
# ------------------------------
# IMPORTANT: Log init must happen before other imports to catch startup issues.

import os
import sys
from pathlib import Path
from datetime import datetime

APP_NAME = "NotesToNotion"
APP_VERSION = "v0.2.1"

LOG_DIR = Path.home() / "Library" / "Application Support" / "NotesToNotion"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "app.log"

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass

log("=== App starting ===")
log(f"Python: {sys.version}")
log(f"Executable: {sys.executable}")

# ------------------------------
# Normal imports (may crash in bundles; logging above helps)
# ------------------------------
import io
import json
import re
import time
import subprocess
from typing import Optional

import rumps
import keyring
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from openai import OpenAI

from PIL import Image

# HEIC support is best-effort; do not crash app if pillow_heif fails in bundle.
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_OK = True
    log("pillow_heif OK")
except Exception as e:
    HEIC_OK = False
    log(f"pillow_heif NOT available: {repr(e)}")

SERVICE_NAME = "com.notes-to-notion"

CONFIG_DIR = LOG_DIR
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


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text("utf-8"))


def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")


def state_load() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text("utf-8"))
        except Exception:
            return {"processed": {}}
    return {"processed": {}}


def state_save(state: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")


def keychain_set(name: str, value: str) -> None:
    keyring.set_password(SERVICE_NAME, name, value)


def keychain_get(name: str) -> Optional[str]:
    return keyring.get_password(SERVICE_NAME, name)


def extract_notion_page_id(input_str: str) -> str:
    """
    Accepts Notion URL or raw page id.
    Extracts 32 hex chars and returns dashed UUID.
    """
    s = (input_str or "").strip()
    s = s.split("?")[0]
    m = re.search(r"([0-9a-fA-F]{32})", s.replace("-", ""))
    if not m:
        raise ValueError("Could not find a valid Notion page ID in the URL/text.")
    raw = m.group(1).lower()
    return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"


def image_to_jpeg_bytes(path: Path) -> bytes:
    """
    Convert image to JPEG bytes.
    If HEIC can't be opened via pillow_heif in a bundle, fallback to macOS `sips`.
    """
    suffix = path.suffix.lower()
    if suffix == ".heic" and not HEIC_OK:
        tmp = Path("/tmp") / (path.stem + ".jpg")
        subprocess.run(["sips", "-s", "format", "jpeg", str(path), "--out", str(tmp)], check=True)
        img = Image.open(tmp)
    else:
        img = Image.open(path)

    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def jpeg_to_data_url(b: bytes) -> str:
    import base64
    return "data:image/jpeg;base64," + base64.b64encode(b).decode("utf-8")


def date_mention_rich_text(dt: datetime):
    # Notion date mention: ISO8601 with local timezone
    iso = dt.astimezone().isoformat(timespec="minutes")
    return [{
        "type": "mention",
        "mention": {"type": "date", "date": {"start": iso}}
    }]


def rt_text(s: str):
    return [{"type": "text", "text": {"content": s}}]


class NotionClient:
    def __init__(self, token: str):
        self.token = token
        self.base = "https://api.notion.com/v1"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def append_children(self, block_id: str, children: list) -> None:
        url = f"{self.base}/blocks/{block_id}/children"
        r = requests.patch(url, headers=self._headers(), data=json.dumps({"children": children}))
        if r.status_code >= 300:
            raise RuntimeError(f"Notion error {r.status_code}: {r.text}")


class Pipeline:
    def __init__(self, openai_key: str, model: str, notion_token: str, page_id: str, status_cb):
        self.client = OpenAI(api_key=openai_key)
        self.model = model
        self.notion = NotionClient(notion_token)
        self.page_id = page_id
        self.status_cb = status_cb
        self.state = state_load()

    def fingerprint(self, path: Path) -> str:
        import hashlib
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def seen(self, fp: str) -> bool:
        return fp in self.state.get("processed", {})

    def mark(self, fp: str, name: str) -> None:
        self.state.setdefault("processed", {})[fp] = {"name": name, "ts": time.time()}
        state_save(self.state)

    def transcribe(self, path: Path) -> dict:
        jpeg = image_to_jpeg_bytes(path)
        data_url = jpeg_to_data_url(jpeg)

        self.status_cb(f"Transcribing: {path.name}")
        log(f"Transcribing: {path}")

        resp = self.client.responses.create(
            model=self.model,
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": PROMPT},
                    {"type": "input_image", "image_url": data_url},
                ],
            }],
        )

        ot = getattr(resp, "output_text", "")
        out = ot() if callable(ot) else ot
        out = (out or "").strip()
        start = out.find("{")
        end = out.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise RuntimeError("Model did not return valid JSON.")
        return json.loads(out[start:end + 1])

    def notion_blocks(self, parsed: dict, filename: str) -> list:
        blocks = []
        dt = datetime.now()

        # Heading with Notion @date mention
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

        topics = parsed.get("topics") or [{"title": "General", "tasks": [], "notes": [], "questions": []}]
        for t in topics:
            title = (t.get("title") or "General").strip() or "General"
            blocks.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": rt_text(title)}})

            for task in (t.get("tasks") or []):
                text = (task.get("text") or "").strip()
                if text:
                    blocks.append({
                        "object": "block",
                        "type": "to_do",
                        "to_do": {"rich_text": rt_text(text), "checked": bool(task.get("done", False))}
                    })

            for note in (t.get("notes") or []):
                note = str(note).strip()
                if note:
                    blocks.append({
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {"rich_text": rt_text(note)}
                    })

            for q in (t.get("questions") or []):
                q = str(q).strip()
                if q:
                    blocks.append({"object": "block", "type": "toggle", "toggle": {"rich_text": rt_text(f"Q: {q}")}})

            blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt_text("")}})

        return blocks

    def process(self, path: Path) -> None:
        fp = self.fingerprint(path)
        if self.seen(fp):
            self.status_cb(f"Already processed: {path.name}")
            log(f"Already processed: {path}")
            return

        parsed = self.transcribe(path)
        self.status_cb(f"Appending: {path.name}")
        log(f"Appending: {path}")

        blocks = self.notion_blocks(parsed, path.name)

        # chunk to avoid payload limits
        chunk = 60
        for i in range(0, len(blocks), chunk):
            self.notion.append_children(self.page_id, blocks[i:i + chunk])
            time.sleep(0.1)

        self.mark(fp, path.name)
        self.status_cb(f"Done: {path.name}")
        log(f"Done: {path}")


class FolderHandler(FileSystemEventHandler):
    def __init__(self, pipeline: Pipeline, watch: Path, status_cb):
        self.pipeline = pipeline
        self.watch = watch
        self.status_cb = status_cb
        self.proc = watch / "_processed"
        self.fail = watch / "_failed"
        self.proc.mkdir(exist_ok=True)
        self.fail.mkdir(exist_ok=True)

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)

        if path.name.startswith("."):
            return
        if path.suffix.lower() not in SUPPORTED_EXTS:
            return

        # wait for file to finish writing
        last = -1
        for _ in range(60):
            try:
                sz = path.stat().st_size
            except FileNotFoundError:
                return
            if sz > 0 and sz == last:
                break
            last = sz
            time.sleep(0.25)

        try:
            self.pipeline.process(path)
            path.replace(self.proc / path.name)
        except Exception as e:
            self.status_cb(f"Error: {e}")
            log(f"ERROR processing {path}: {repr(e)}")
            try:
                path.replace(self.fail / path.name)
            except Exception:
                pass


class NotesMenuApp(rumps.App):
    def __init__(self):
        # Disable default Quit to avoid duplicate Quit entries.
        super().__init__(APP_NAME, quit_button=None)
        self.title = "📷📝"

        self.status_msg = "Idle"
        self.observer: Optional[Observer] = None

        self.mi_start = rumps.MenuItem("Start Watching", callback=self.start_watching)
        self.mi_stop = rumps.MenuItem("Stop Watching", callback=self.stop_watching)
        self.mi_setup = rumps.MenuItem("Setup…", callback=self.setup)
        self.mi_status = rumps.MenuItem("Status…", callback=self.show_status)
        self.mi_open_watch = rumps.MenuItem("Open Watch Folder", callback=self.open_watch_folder)
        self.mi_open_failed = rumps.MenuItem("Open _failed", callback=self.open_failed)
        self.mi_open_log = rumps.MenuItem("Open Log", callback=self.open_log)
        self.mi_about = rumps.MenuItem(f"About ({APP_VERSION})", callback=self.about)
        self.mi_quit = rumps.MenuItem("Quit", callback=self.quit_app)

        self.menu = [
            self.mi_start,
            self.mi_stop,
            None,
            self.mi_setup,
            self.mi_status,
            self.mi_open_watch,
            self.mi_open_failed,
            self.mi_open_log,
            None,
            self.mi_about,
            self.mi_quit,
        ]

        self._refresh_menu_states()
        log("Menu initialized")

    def status_cb(self, msg: str):
        self.status_msg = msg
        log(f"STATUS: {msg}")

    def _refresh_menu_states(self):
        running = self.observer is not None
        self.mi_start.state = 1 if running else 0

    def _ensure_config(self) -> Optional[dict]:
        cfg = load_config()
        openai_key = keychain_get("OPENAI_API_KEY")
        notion_token = keychain_get("NOTION_TOKEN")
        if not cfg.get("WATCH_FOLDER") or not cfg.get("NOTION_PAGE_ID") or not openai_key or not notion_token:
            return None
        return cfg

    def setup(self, _):
        cfg = load_config()

        w = rumps.Window(
            title="Watch folder path",
            message="Example: /Users/you/NotesDrop",
            default_text=cfg.get("WATCH_FOLDER", ""),
            ok="Next",
            cancel="Cancel"
        ).run()
        if not w.clicked:
            return

        nurl = rumps.Window(
            title="Notion page URL",
            message="Paste the Notion page link (URL).",
            default_text=cfg.get("NOTION_PAGE_URL", ""),
            ok="Next",
            cancel="Cancel"
        ).run()
        if not nurl.clicked:
            return

        notion_tok = rumps.Window(
            title="Notion integration token",
            message="Saved to Keychain. Leave blank to keep existing.",
            default_text="",
            ok="Next",
            cancel="Cancel"
        ).run()
        if not notion_tok.clicked:
            return

        openai = rumps.Window(
            title="OpenAI API key",
            message="Saved to Keychain. Leave blank to keep existing.",
            default_text="",
            ok="Save",
            cancel="Cancel"
        ).run()
        if not openai.clicked:
            return

        try:
            page_id = extract_notion_page_id(nurl.text)
        except Exception as e:
            log(f"Bad Notion URL: {repr(e)}")
            rumps.alert("Bad Notion URL", str(e))
            return

        cfg["WATCH_FOLDER"] = w.text.strip()
        cfg["NOTION_PAGE_URL"] = nurl.text.strip()
        cfg["NOTION_PAGE_ID"] = page_id
        cfg.setdefault("OPENAI_MODEL", "gpt-5.2")
        save_config(cfg)

        if notion_tok.text.strip():
            keychain_set("NOTION_TOKEN", notion_tok.text.strip())
        if openai.text.strip():
            keychain_set("OPENAI_API_KEY", openai.text.strip())

        self.status_msg = "Saved setup."
        log("Setup saved")
        rumps.alert("Saved", "Setup saved. Now click Start Watching.")

    def start_watching(self, _):
        if self.observer is not None:
            rumps.alert("Already running", "Watcher is already running.")
            return

        cfg = self._ensure_config()
        if not cfg:
            rumps.alert("Setup needed", "Click Setup… and paste folder + Notion URL + keys.")
            return

        watch = Path(cfg["WATCH_FOLDER"]).expanduser()
        watch.mkdir(parents=True, exist_ok=True)

        openai_key = keychain_get("OPENAI_API_KEY")
        notion_token = keychain_get("NOTION_TOKEN")

        try:
            pipeline = Pipeline(
                openai_key=openai_key,
                model=cfg.get("OPENAI_MODEL", "gpt-5.2"),
                notion_token=notion_token,
                page_id=cfg["NOTION_PAGE_ID"],
                status_cb=self.status_cb
            )
            handler = FolderHandler(pipeline, watch, self.status_cb)

            self.observer = Observer()
            self.observer.schedule(handler, str(watch), recursive=False)
            self.observer.start()

            self.status_msg = f"Watching: {watch}"
            log(f"Watching: {watch}")
            rumps.notification(APP_NAME, "Started", str(watch))
        except Exception as e:
            self.observer = None
            log(f"Could not start watcher: {repr(e)}")
            rumps.alert("Could not start", str(e))
        finally:
            self._refresh_menu_states()

    def stop_watching(self, _):
        if self.observer is None:
            rumps.alert("Not running", "Watcher is not running.")
            return

        try:
            self.observer.stop()
            self.observer.join(timeout=5)
        finally:
            self.observer = None
            self.status_msg = "Stopped."
            log("Stopped watcher")
            rumps.notification(APP_NAME, "Stopped", "")
            self._refresh_menu_states()

    def show_status(self, _):
        rumps.alert("Status", self.status_msg or "—")

    def open_watch_folder(self, _):
        cfg = load_config()
        p = cfg.get("WATCH_FOLDER")
        if p:
            subprocess.run(["open", p])

    def open_failed(self, _):
        cfg = load_config()
        p = cfg.get("WATCH_FOLDER")
        if p:
            subprocess.run(["open", str(Path(p) / "_failed")])

    def open_log(self, _):
        subprocess.run(["open", str(LOG_FILE)])

    def about(self, _):
        cfg = load_config()
        model = cfg.get("OPENAI_MODEL", "gpt-5.2")
        msg = "\n".join([
            f"{APP_NAME} {APP_VERSION}",
            "",
            f"Log: {LOG_FILE}",
            f"Config: {CONFIG_PATH}",
            f"Model: {model}",
        ])
        rumps.alert("About", msg)

    def quit_app(self, _):
        try:
            if self.observer is not None:
                self.observer.stop()
                self.observer.join(timeout=2)
        finally:
            log("Quit")
            rumps.quit_application()


if __name__ == "__main__":
    try:
        NotesMenuApp().run()
    except Exception as e:
        log(f"FATAL: {repr(e)}")
        raise