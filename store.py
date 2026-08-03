"""
HEAVEN verification store — JSON file persistence.
Tracks applications so tickets survive restarts and mods have a queue.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any

# data/ next to this file
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
STORE_PATH = os.path.join(DATA_DIR, "verifications.json")

_lock = threading.Lock()

# status values:
#   pending      — form submitted, waiting on mod
#   needs_info   — mod asked for more (e.g. selfie)
#   approved     — verified
#   denied       — denied but may reapply later
#   kicked       — rejected + kicked
#   banned       — rejected + banned
#   closed       — ticket closed without decision
#   expired      — auto-closed as stale

OPEN_STATUSES = {"pending", "needs_info"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty() -> dict[str, Any]:
    return {"version": 1, "applications": {}, "meta": {"queue_message_id": None}}


def ensure_store() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.isfile(STORE_PATH):
        _write(_empty())


def _read() -> dict[str, Any]:
    ensure_store()
    with _lock:
        try:
            with open(STORE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = _empty()
        if "applications" not in data:
            data = _empty()
        return data


def _write(data: dict[str, Any]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = STORE_PATH + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, STORE_PATH)


def get_app(user_id: int) -> dict[str, Any] | None:
    data = _read()
    return data["applications"].get(str(user_id))


def upsert_app(user_id: int, **fields) -> dict[str, Any]:
    data = _read()
    key = str(user_id)
    app = data["applications"].get(key) or {
        "user_id": user_id,
        "created_at": _now_iso(),
        "status": "pending",
        "history": [],
    }
    app.update(fields)
    app["updated_at"] = _now_iso()
    data["applications"][key] = app
    _write(data)
    return app


def add_history(user_id: int, event: str, by: int | None = None, note: str = "") -> None:
    data = _read()
    key = str(user_id)
    app = data["applications"].get(key)
    if not app:
        return
    app.setdefault("history", []).append({
        "at": _now_iso(),
        "event": event,
        "by": by,
        "note": note[:300],
    })
    # keep last 30 events
    app["history"] = app["history"][-30:]
    app["updated_at"] = _now_iso()
    data["applications"][key] = app
    _write(data)


def set_status(user_id: int, status: str, by: int | None = None, note: str = "", **extra) -> dict[str, Any] | None:
    data = _read()
    key = str(user_id)
    app = data["applications"].get(key)
    if not app:
        app = {
            "user_id": user_id,
            "created_at": _now_iso(),
            "history": [],
        }
    app["status"] = status
    app["updated_at"] = _now_iso()
    if by is not None:
        app["decided_by"] = by
    if note:
        app["decision_note"] = note[:500]
    app.update(extra)
    app.setdefault("history", []).append({
        "at": _now_iso(),
        "event": status,
        "by": by,
        "note": note[:300],
    })
    app["history"] = app["history"][-30:]
    data["applications"][key] = app
    _write(data)
    return app


def list_open() -> list[dict[str, Any]]:
    data = _read()
    apps = [
        a for a in data["applications"].values()
        if a.get("status") in OPEN_STATUSES
    ]
    apps.sort(key=lambda a: a.get("created_at") or "")
    return apps


def list_by_status(status: str) -> list[dict[str, Any]]:
    data = _read()
    return [a for a in data["applications"].values() if a.get("status") == status]


def count_open() -> int:
    return len(list_open())


def get_queue_message_id() -> int | None:
    data = _read()
    mid = data.get("meta", {}).get("queue_message_id")
    return int(mid) if mid else None


def set_queue_message_id(message_id: int | None) -> None:
    data = _read()
    data.setdefault("meta", {})["queue_message_id"] = message_id
    _write(data)


def has_open_application(user_id: int) -> bool:
    app = get_app(user_id)
    return bool(app and app.get("status") in OPEN_STATUSES)


def is_banned_record(user_id: int) -> bool:
    app = get_app(user_id)
    return bool(app and app.get("status") == "banned")


def increment_field(user_id: int, field: str, amount: int = 1) -> int:
    """Increment a numeric field and return the new value."""
    app = get_app(user_id) or {}
    current = app.get(field, 0)
    new_val = current + amount
    upsert_app(user_id, **{field: new_val})
    return new_val

