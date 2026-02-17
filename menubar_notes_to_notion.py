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
from typing import Optional, List

import rumps
import keyring
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from openai import OpenAI

from PIL import Image

from prompt_contract import PROMPT
from notion_format import build_notion_blocks

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


class NotionClient:
    def __init__(self, token: str):
        self.token = token
        self.base = "https://api.notion.com/v1"

    def _headers_json(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _headers_no_ct(self) -> dict:
        # For multipart/form-data requests, DO NOT set Content-Type manually.
        return {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": NOTION_VERSION,
        }

    def list_children_ids(self, block_id: str, page_size: int = 50) -> List[str]:
        url = f"{self.base}/blocks/{block_id}/children?page_size={page_size}"
        r = requests.get(url, headers=self._headers_no_ct())
        if r.status_code >= 300:
            raise RuntimeError(f"Notion list children error {r.status_code}: {r.text}")
        results = (r.json() or {}).get("results", [])
        return [b.get("id") for b in results if b.get("id")]

    def find_first_h1_id(self, page_id: str, page_size: int = 50) -> Optional[str]:
        url = f"{self.base}/blocks/{page_id}/children?page_size={page_size}"
        r = requests.get(url, headers=self._headers_no_ct())
        if r.status_code >= 300:
            raise RuntimeError(f"Notion list children error {r.status_code}: {r.text}")
        results = (r.json() or {}).get("results", [])

        for b in results:
            if b.get("type") == "heading_1":
                return b.get("id")
        return None

    def append_children(self, block_id: str, children: list, after_block_id: Optional[str] = None) -> None:
        url = f"{self.base}/blocks/{block_id}/children"
        payload = {"children": children}
        if after_block_id:
            payload["after"] = after_block_id

        r = requests.patch(url, headers=self._headers_json(), data=json.dumps(payload))
        if r.status_code >= 300:
            raise RuntimeError(f"Notion append error {r.status_code}: {r.text}")

    # ---- File Upload API (single part, <= 20MB) ----

    def create_file_upload(self, filename: str, content_type: str, content_length: int) -> dict:
        url = f"{self.base}/file_uploads"
        payload = {
            "mode": "single_part",
            "filename": filename,
            "content_type": content_type,
            "content_length": int(content_length),
        }
        r = requests.post(url, headers=self._headers_json(), data=json.dumps(payload))
        if r.status_code >= 300:
            raise RuntimeError(f"Notion create file upload error {r.status_code}: {r.text}")
        return r.json()

    def send_file_upload(self, file_upload_id: str, filename: str, content_type: str, data: bytes) -> dict:
        url = f"{self.base}/file_uploads/{file_upload_id}/send"
        files = {"file": (filename, data, content_type)}
        r = requests.post(url, headers=self._headers_no_ct(), files=files)
        if r.status_code >= 300:
            raise RuntimeError(f"Notion send file upload error {r.status_code}: {r.text}")
        return r.json()

    def upload_image_bytes(self, filename: str, data: bytes, content_type: str = "image/jpeg") -> str:
        fu = self.create_file_upload(filename=filename, content_type=content_type, content_length=len(data))
        file_upload_id = fu.get("id")
        if not file_upload_id:
            raise RuntimeError("Notion file upload did not return an id.")

        self.send_file_upload(
            file_upload_id=file_upload_id,
            filename=filename,
            content_type=content_type,
            data=data,
        )
        return file_upload_id


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

    def transcribe_from_jpeg(self, jpeg_bytes: bytes, filename: str) -> dict:
        data_url = jpeg_to_data_url(jpeg_bytes)

        self.status_cb(f"Transcribing: {filename}")
        log(f"Transcribing: {filename}")

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

    def process(self, path: Path) -> None:
        fp = self.fingerprint(path)
        if self.seen(fp):
            self.status_cb(f"Already processed: {path.name}")
            log(f"Already processed: {path}")
            return

        jpeg_bytes = image_to_jpeg_bytes(path)

        # Upload image for attachment (best effort)
        image_file_upload_id = None
        try:
            self.status_cb(f"Uploading image: {path.name}")
            log(f"Uploading image to Notion: {path}")
            upload_name = f"{path.stem}.jpg"
            image_file_upload_id = self.notion.upload_image_bytes(
                filename=upload_name,
                data=jpeg_bytes,
                content_type="image/jpeg",
            )
            log(f"Uploaded image file_upload_id: {image_file_upload_id}")
        except Exception as e:
            image_file_upload_id = None
            log(f"Image upload failed (continuing without attachment): {repr(e)}")

        parsed = self.transcribe_from_jpeg(jpeg_bytes, path.name)

        self.status_cb(f"Appending: {path.name}")
        log(f"Appending: {path}")

        # ✅ Single source of truth (unit-tested)
        blocks = build_notion_blocks(
            parsed=parsed,
            filename=path.name,
            image_upload_id=image_file_upload_id,
            now=datetime.now(),
        )

        # Insert after first H1
        try:
            after_id = self.notion.find_first_h1_id(self.page_id)
            if not after_id:
                child_ids = self.notion.list_children_ids(self.page_id, page_size=50)
                after_id = child_ids[0] if child_ids else None
        except Exception as e:
            after_id = None
            log(f"Could not resolve insert-after; fallback to append: {repr(e)}")

        chunk = 60
        for i in range(0, len(blocks), chunk):
            self.notion.append_children(self.page_id, blocks[i:i + chunk], after_block_id=after_id)
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

        try:
            cfg = self._ensure_config()
            if cfg:
                # Run after menubar is up (avoid startup flakiness)
                rumps.Timer(self._autostart_watch, 1).start()
                log("Auto-start scheduled")
            else:
                log("Auto-start skipped (missing config/keys)")
        except Exception as e:
            log(f"Auto-start error (ignored): {repr(e)}")

    def status_cb(self, msg: str):
        self.status_msg = msg
        log(f"STATUS: {msg}")

    def _autostart_watch(self, _):
        # Timer callback signature includes a timer arg we don't need
        if self.observer is not None:
            return
        try:
            self.start_watching(None)
        except Exception as e:
            log(f"Auto-start failed: {repr(e)}")

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
