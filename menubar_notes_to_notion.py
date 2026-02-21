# ------------------------------
# NotesToNotion v0.2.1
# ------------------------------
# IMPORTANT: Log init must happen before other imports to catch startup issues.

import os
import sys
from pathlib import Path
from datetime import datetime
from app_contract import APP_NAME, APP_VERSION, NOTION_VERSION, DEFAULT_OPENAI_MODEL
from prompt_contract import PROMPT
from usage_tracker import (
    append_event as usage_append_event,
    aggregates as usage_aggregates,
    load_usage as usage_load,
)

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

DEBUG_LOGGING = os.getenv("NOTES_TO_NOTION_DEBUG", "").strip() == "1"


def log_debug(msg: str) -> None:
    if DEBUG_LOGGING:
        log(msg)


log("=== App starting ===")
log(f"Python: {sys.version}")
log(f"Executable: {sys.executable}")
log(f"Model: {DEFAULT_OPENAI_MODEL}")

# ------------------------------
# Normal imports (may crash in bundles; logging above helps)
# ------------------------------
import io
import json
import re
import time
import subprocess
import threading
import uuid
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

try:
    from Foundation import NSObject
    from AppKit import NSUserNotification, NSUserNotificationCenter
except Exception:
    NSObject = object
    NSUserNotification = None
    NSUserNotificationCenter = None

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
USAGE_PATH = CONFIG_DIR / "usage.json"

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
NOTION_VERSION = NOTION_VERSION

def list_pending_images(watch: Path) -> List[Path]:
    """
    List supported images in the watch folder root (not recursive), excluding hidden files
    and excluding the _processed/_failed directories.
    Returns sorted by mtime (oldest first) for deterministic batching.
    """
    pending: List[Path] = []
    for p in watch.iterdir():
        if p.is_dir():
            continue
        if p.name.startswith("."):
            continue
        if p.suffix.lower() not in SUPPORTED_EXTS:
            continue
        pending.append(p)

    pending.sort(key=lambda x: (x.stat().st_mtime, x.name))
    return pending


def get_failed_count(watch_folder: Optional[Path]) -> int:
    if not watch_folder:
        return 0
    failed_dir = watch_folder / "_failed"
    if not failed_dir.exists() or not failed_dir.is_dir():
        return 0
    try:
        return sum(1 for p in failed_dir.iterdir() if p.is_file() and not p.name.startswith("."))
    except Exception:
        return 0


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


def usage_int(usage: object, field: str) -> int:
    if usage is None:
        return 0
    if isinstance(usage, dict):
        val = usage.get(field)
    else:
        val = getattr(usage, field, None)
    try:
        return max(int(val), 0)
    except Exception:
        return 0


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

    w, h = img.size
    longest = max(w, h)
    if longest > 1800:
        scale = 1800 / float(longest)
        nw = max(1, int(round(w * scale)))
        nh = max(1, int(round(h * scale)))
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)

    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75)
    return buf.getvalue()


def jpeg_to_data_url(b: bytes) -> str:
    import base64
    return "data:image/jpeg;base64," + base64.b64encode(b).decode("utf-8")


def notion_id_without_dashes(raw_id: str) -> str:
    return (raw_id or "").replace("-", "")


def build_notion_block_url(block_id: str) -> str:
    return f"https://www.notion.so/{notion_id_without_dashes(block_id)}"


def build_notion_page_anchor_url(page_id: str, block_id: str) -> str:
    return f"https://www.notion.so/{notion_id_without_dashes(page_id)}#{notion_id_without_dashes(block_id)}"


def first_h2_section_title(blocks: list) -> Optional[str]:
    for block in (blocks or []):
        if block.get("type") != "heading_2":
            continue
        rt = ((block.get("heading_2") or {}).get("rich_text") or [])
        text = "".join(
            ((p.get("text") or {}).get("content") or "")
            for p in rt
            if p.get("type") == "text"
        ).strip()
        if text.startswith("—"):
            text = text[1:].strip()
        elif text.startswith("-"):
            text = text[1:].strip()
        return text or None
    return None


def extract_first_h2_block_id_from_append_response(resp: dict, chunk_blocks: Optional[list] = None) -> Optional[str]:
    results = (resp or {}).get("results", []) or []
    for b in results:
        if b.get("type") == "heading_2" and b.get("id"):
            return b.get("id")

    # Fallback mapping by position when Notion response omits block type.
    if chunk_blocks and results:
        for idx, src in enumerate(chunk_blocks):
            if src.get("type") == "heading_2" and idx < len(results):
                mapped = (results[idx] or {}).get("id")
                if mapped:
                    return mapped

    # Last-resort fallback: first created block id.
    if results and results[0].get("id"):
        return results[0].get("id")
    return None


def _success_notification_identifier(filename: str) -> str:
    name = (filename or "").strip() or "image"
    return f"success-{name}-{uuid.uuid4().hex[:12]}"


def notify_processed_image(section_title: Optional[str], filename: str, url: Optional[str]) -> None:
    title = (section_title or "").strip()
    detail = title if title and title != "Handwritten notes" else (filename or "").strip() or "Notat"
    identifier = _success_notification_identifier(filename)
    notify("Notat lagt til", detail, url, identifier=identifier)


_failed_notification_paths = set()
_failed_notification_lock = threading.Lock()


def _failure_reason_short(exc: Optional[Exception]) -> str:
    message = ""
    if exc is not None:
        message = (str(exc) or "").strip()
    if message:
        message = message.splitlines()[0].strip()
    return message or "Ukjent feil"


def notify_failed_image(path: Path, exc: Optional[Exception]) -> None:
    try:
        key = str(path.expanduser().resolve())
    except Exception:
        key = str(path)

    with _failed_notification_lock:
        if key in _failed_notification_paths:
            return
        _failed_notification_paths.add(key)

    reason = _failure_reason_short(exc)
    body = f"{path.name} — {reason}" if path.name else reason
    body = body[:120]
    try:
        notify("Notat feilet", body, None, identifier=f"failed-{uuid.uuid4().hex[:12]}")
    except Exception as e:
        log(f"Failure notification error: {repr(e)}")


class NotificationCenterDelegate(NSObject):
    def userNotificationCenter_didActivateNotification_(self, center, notification):
        try:
            info = notification.userInfo() if hasattr(notification, "userInfo") else None
            url = info.get("url") if isinstance(info, dict) else None
            if url:
                subprocess.run(["open", url])
        except Exception as e:
            log(f"Could not open notification url: {repr(e)}")


_notification_delegate = None
_pending_notify_timers = []


def ensure_notification_center_delegate() -> None:
    global _notification_delegate
    if NSUserNotificationCenter is None or _notification_delegate is not None:
        return
    try:
        center = NSUserNotificationCenter.defaultUserNotificationCenter()
        _notification_delegate = NotificationCenterDelegate.alloc().init()
        center.setDelegate_(_notification_delegate)
    except Exception as e:
        log(f"Could not set notification center delegate: {repr(e)}")


def notify(title: str, body: str, url: Optional[str], identifier: Optional[str] = None) -> None:
    if NSUserNotificationCenter is None or NSUserNotification is None:
        log("NSUserNotificationCenter unavailable; skipping notification")
        return

    title_text = (title or "").strip() or "Notat lagt til"
    body_text = (body or "").strip() or "Notat"
    note_identifier = (identifier or "").strip() or f"note-{uuid.uuid4().hex[:12]}"

    try:
        ensure_notification_center_delegate()
        center = NSUserNotificationCenter.defaultUserNotificationCenter()
        note = NSUserNotification.alloc().init()
        note.setTitle_(title_text)
        note.setInformativeText_(body_text)
        if hasattr(note, "setSoundName_"):
            note.setSoundName_(None)
        if hasattr(note, "setIdentifier_"):
            note.setIdentifier_(note_identifier)
        if url:
            note.setUserInfo_({"url": url})
        center.deliverNotification_(note)
    except Exception as e:
        log(f"Notification error: {repr(e)}")


def dispatch_processed_image_notification(section_title: Optional[str], filename: str, url: Optional[str]) -> None:
    if threading.current_thread().name == "MainThread":
        notify_processed_image(section_title, filename, url)
        return

    def _one_shot(timer):
        try:
            timer.stop()
        except Exception:
            pass
        notify_processed_image(section_title, filename, url)

    rumps.Timer(_one_shot, 0).start()


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
        """
        Returns child block IDs in order (top to bottom), paginating until done.
        """
        ids: List[str] = []
        cursor = None

        while True:
            url = f"{self.base}/blocks/{block_id}/children?page_size={page_size}"
            if cursor:
                url += f"&start_cursor={cursor}"

            r = requests.get(url, headers=self._headers_no_ct())
            if r.status_code >= 300:
                raise RuntimeError(f"Notion list children error {r.status_code}: {r.text}")

            data = r.json() or {}
            results = data.get("results", []) or []
            ids.extend([b.get("id") for b in results if b.get("id")])

            if not data.get("has_more"):
                break

            cursor = data.get("next_cursor")
            if not cursor:
                break

        return ids

    def find_first_h1_id(self, page_id: str, page_size: int = 50) -> Optional[str]:
        """
        Returns the id of the first heading_1 block among the page's top-level children.
        Paginates until found or no more results.
        """
        cursor = None

        while True:
            url = f"{self.base}/blocks/{page_id}/children?page_size={page_size}"
            if cursor:
                url += f"&start_cursor={cursor}"

            r = requests.get(url, headers=self._headers_no_ct())
            if r.status_code >= 300:
                raise RuntimeError(f"Notion list children error {r.status_code}: {r.text}")

            data = r.json() or {}
            results = data.get("results", []) or []

            for b in results:
                if b.get("type") == "heading_1":
                    return b.get("id")

            if not data.get("has_more"):
                return None

            cursor = data.get("next_cursor")
            if not cursor:
                return None

    def append_children(self, block_id: str, children: list, after_block_id: Optional[str] = None) -> dict:
        url = f"{self.base}/blocks/{block_id}/children"
        payload = {"children": children}
        if after_block_id:
            payload["after"] = after_block_id

        r = requests.patch(url, headers=self._headers_json(), data=json.dumps(payload))
        if r.status_code >= 300:
            raise RuntimeError(f"Notion append error {r.status_code}: {r.text}")
        return r.json()

    def get_block(self, block_id: str) -> dict:
        url = f"{self.base}/blocks/{block_id}"
        r = requests.get(url, headers=self._headers_no_ct())
        if r.status_code >= 300:
            raise RuntimeError(f"Notion get block error {r.status_code}: {r.text}")
        return r.json() or {}

    def resolve_parent_page_id(self, block_id: str) -> Optional[str]:
        current_block_id = block_id
        for _ in range(10):
            block = self.get_block(current_block_id) or {}
            parent = block.get("parent") or {}
            parent_type = parent.get("type")
            if parent_type == "page_id":
                return parent.get("page_id")
            if parent_type == "block_id" and parent.get("block_id"):
                current_block_id = parent.get("block_id")
                continue
            return None
        return None

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
        self._last_usage = None

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
        usage = getattr(resp, "usage", None)
        if usage is None:
            log(f"OpenAI response missing usage for {filename}; defaulting token counts to 0")
        self._last_usage = {
            "model": getattr(resp, "model", None) or self.model,
            "input_tokens": usage_int(usage, "input_tokens"),
            "output_tokens": usage_int(usage, "output_tokens"),
        }

        ot = getattr(resp, "output_text", "")
        out = ot() if callable(ot) else ot
        out = (out or "").strip()

        start = out.find("{")
        end = out.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise RuntimeError("Model did not return valid JSON.")
        return json.loads(out[start:end + 1])

    def record_usage(self, filename: str) -> None:
        usage = self._last_usage or {}
        event = {
            "ts": time.time(),
            "model": usage.get("model") or self.model,
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "filename": filename,
        }
        try:
            usage_append_event(USAGE_PATH, event)
        except Exception as e:
            log(f"Usage tracking failed: {repr(e)}")

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
        self.record_usage(path.name)

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

        first_h2_block_id = None
        chunk = 60
        for i in range(0, len(blocks), chunk):
            chunk_blocks = blocks[i:i + chunk]
            resp = self.notion.append_children(self.page_id, chunk_blocks, after_block_id=after_id)
            if first_h2_block_id is None:
                first_h2_block_id = extract_first_h2_block_id_from_append_response(resp, chunk_blocks)

            # Update after_id so the next chunk is inserted directly after the chunk we just inserted.
            results = (resp or {}).get("results", []) or []
            if results:
                first_new_id = results[0].get("id")
                if first_new_id:
                    after_id = first_new_id

            time.sleep(0.1)

        section_title = first_h2_section_title(blocks)
        # "Last note" points to the first H2 block created for this image.
        note_url = None
        if first_h2_block_id:
            parent_page_id = None
            try:
                parent_page_id = self.notion.resolve_parent_page_id(first_h2_block_id)
            except Exception as e:
                log(f"Could not resolve parent page id: {repr(e)}")
            if parent_page_id:
                note_url = build_notion_page_anchor_url(parent_page_id, first_h2_block_id)
            else:
                note_url = build_notion_block_url(first_h2_block_id)
        if note_url:
            self.state["last_note_url"] = note_url
            self.state["last_note_ts"] = time.time()
            self.state["last_note_title"] = section_title or path.name
        try:
            notify_processed_image(
                section_title,
                path.name,
                note_url,
            )
        except Exception as e:
            log(f"Notification error: {repr(e)}")
        self.mark(fp, path.name)
        self.status_cb(f"Done: {path.name}")
        log(f"Done: {path}")


class FolderHandler(FileSystemEventHandler):
    def __init__(self, pipeline: Pipeline, watch: Path, status_cb, refresh_menu_cb=None):
        self.pipeline = pipeline
        self.watch = watch
        self.status_cb = status_cb
        self.refresh_menu_cb = refresh_menu_cb
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
            notify_failed_image(path, e)
        finally:
            if self.refresh_menu_cb:
                self.refresh_menu_cb()


class NotesMenuApp(rumps.App):
    def __init__(self):
        super().__init__(
            APP_NAME,
            quit_button=None,
            icon="icon.png",
            template=False,
        )

        self.status_msg = "Idle"
        self.observer: Optional[Observer] = None

        self.mi_start = rumps.MenuItem("Start Watching", callback=self.start_watching)
        self.mi_stop = rumps.MenuItem("Stop Watching", callback=self.stop_watching)
        self.mi_setup = rumps.MenuItem("Setup…", callback=self.setup)
        self.mi_status = rumps.MenuItem("Status…", callback=self.show_status)
        self.mi_open_last_note = rumps.MenuItem("Open last note", callback=self.open_last_note)
        self.mi_open_watch = rumps.MenuItem("Open Watch Folder", callback=self.open_watch_folder)
        self.mi_open_log = rumps.MenuItem("Open Log", callback=self.open_log)
        self.mi_about = rumps.MenuItem(f"About ({APP_VERSION})", callback=self.about)
        self.mi_quit = rumps.MenuItem("Quit", callback=self.quit_app)

        self.menu = [
            self.mi_start,
            self.mi_stop,
            None,
            self.mi_setup,
            self.mi_status,
            self.mi_open_last_note,
            self.mi_open_watch,
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
        cfg = load_config()
        watch_folder = cfg.get("WATCH_FOLDER")
        failed_count = get_failed_count(Path(watch_folder).expanduser() if watch_folder else None)
        if failed_count > 0:
            self.mi_open_watch.title = f"Open Watch Folder — {failed_count} failed"
        else:
            self.mi_open_watch.title = "Open Watch Folder"

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
                model=DEFAULT_OPENAI_MODEL,
                notion_token=notion_token,
                page_id=cfg["NOTION_PAGE_ID"],
                status_cb=self.status_cb
            )
            handler = FolderHandler(pipeline, watch, self.status_cb, refresh_menu_cb=self._refresh_menu_states)

            # ✅ Batch existing files on startup (before/after watcher start)
            try:
                pending = list_pending_images(watch)
                if pending:
                    self.status_cb(f"Batch processing {len(pending)} file(s)…")
                    log(f"Batch startup: {len(pending)} file(s)")

                    for p in pending:
                        try:
                            pipeline.process(p)
                            p.replace(handler.proc / p.name)
                        except Exception as e:
                            self.status_cb(f"Error: {e}")
                            log(f"ERROR batch processing {p}: {repr(e)}")
                            try:
                                p.replace(handler.fail / p.name)
                            except Exception:
                                pass
                            notify_failed_image(p, e)
                        finally:
                            self._refresh_menu_states()
            except Exception as e:
                log(f"Batch startup failed (ignored): {repr(e)}")

            self.observer = Observer()
            self.observer.schedule(handler, str(watch), recursive=False)
            self.observer.start()

            self.status_msg = f"Watching: {watch}"
            log(f"Watching: {watch}")
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

    def open_last_note(self, _):
        st = state_load()
        url = st.get("last_note_url")
        if not url:
            rumps.alert("No note yet", "No processed note in this session")
            return
        subprocess.run(["open", url])

    def open_watch_folder(self, _):
        self._refresh_menu_states()
        cfg = load_config()
        p = cfg.get("WATCH_FOLDER")
        if p:
            subprocess.run(["open", p])

    def open_log(self, _):
        subprocess.run(["open", str(LOG_FILE)])

    def about(self, _):
        cfg = load_config()
        watch_folder = cfg.get("WATCH_FOLDER") or "—"
        st = state_load()
        processed = st.get("processed", {})
        processed_count = len(processed) if isinstance(processed, dict) else 0
        usage_data = usage_load(USAGE_PATH)
        usage_events = usage_data.get("events", [])
        agg = usage_aggregates(usage_events, now_ts=time.time())
        images_count = max(processed_count, int(agg.get("count", 0)))
        msg = "\n".join([
            "System:",
            f"{APP_NAME} {APP_VERSION}",
            f"OpenAI model: {DEFAULT_OPENAI_MODEL}",
            f"Notion API: {NOTION_VERSION}",
            f"Watch folder: {watch_folder}",
            "",
            "Usage:",
            f"Images processed: {images_count}",
            f"Estimated cost (lifetime): ${agg.get('total_cost', 0.0):.2f}",
            f"Avg per image: ${agg.get('avg_cost', 0.0):.2f}",
            f"Last 7 days: ${agg.get('last7_cost', 0.0):.2f}",
            "Pricing basis: local estimated token price list",
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
