import json
import threading
import time
from pathlib import Path
from typing import Optional

from app_contract import (
    PRICE_PER_1M_INPUT_TOKENS_USD,
    PRICE_PER_1M_OUTPUT_TOKENS_USD,
)


_WRITE_LOCK = threading.Lock()


def load_usage(path: Path) -> dict:
    if not path.exists():
        return {"events": []}
    try:
        data = json.loads(path.read_text("utf-8"))
    except Exception:
        return {"events": []}
    events = data.get("events")
    if not isinstance(events, list):
        return {"events": []}
    return {"events": events}


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)


def append_event(path: Path, event: dict) -> None:
    with _WRITE_LOCK:
        data = load_usage(path)
        events = data.setdefault("events", [])
        events.append(
            {
                "ts": float(event.get("ts", time.time())),
                "model": event.get("model", ""),
                "input_tokens": int(event.get("input_tokens", 0) or 0),
                "output_tokens": int(event.get("output_tokens", 0) or 0),
                "filename": event.get("filename", ""),
            }
        )
        _atomic_write_json(path, data)


def event_cost_usd(event: dict) -> float:
    input_tokens = max(int(event.get("input_tokens", 0) or 0), 0)
    output_tokens = max(int(event.get("output_tokens", 0) or 0), 0)
    return (
        (input_tokens * PRICE_PER_1M_INPUT_TOKENS_USD)
        + (output_tokens * PRICE_PER_1M_OUTPUT_TOKENS_USD)
    ) / 1_000_000.0


def aggregates(events: list, now_ts: Optional[float] = None) -> dict:
    now = float(now_ts if now_ts is not None else time.time())
    cutoff = now - (7 * 24 * 60 * 60)

    count = len(events)
    total_cost = sum(event_cost_usd(e) for e in events)
    avg_cost = (total_cost / count) if count > 0 else 0.0
    last7_cost = sum(
        event_cost_usd(e)
        for e in events
        if float(e.get("ts", 0.0) or 0.0) >= cutoff
    )

    return {
        "count": count,
        "total_cost": total_cost,
        "avg_cost": avg_cost,
        "last7_cost": last7_cost,
    }
