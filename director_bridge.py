# twitch_service/director_bridge.py
"""
Socket.IO CLIENT that connects to the Director Engine (port 8002).

Responsibilities:
  - Forward incoming Twitch chat as `twitch_message` + `event` socket events
  - Listen for `bot_reply` broadcast and hand it to a callback so the
    Twitch client can post it back to chat
"""
import socketio
import threading
import time
from typing import Callable, Optional

from config import DIRECTOR_URL, BOT_NAME

sio = socketio.Client(
    reconnection=True,
    reconnection_attempts=0,
    reconnection_delay=2,
    reconnection_delay_max=10,
    logger=False,
    engineio_logger=False,
)

_on_bot_reply_cb: Optional[Callable] = None
_is_running = False
_connector_thread: Optional[threading.Thread] = None


# ─────────────────────────────────────────────
# Socket.IO event handlers
# ─────────────────────────────────────────────

@sio.event
def connect():
    print("[DirectorBridge] ✅ Connected to Director Engine")


@sio.event
def connect_error(data):
    print(f"[DirectorBridge] 🔥 Connection error: {data}")


@sio.event
def disconnect():
    print("[DirectorBridge] 🔌 Disconnected from Director Engine")


@sio.on("bot_reply")
def on_bot_reply(data):
    """
    Director broadcasts bot_reply to all connected clients.
    We pick it up here and forward it to Twitch chat.
    """
    if _on_bot_reply_cb:
        _on_bot_reply_cb(data)


# ─────────────────────────────────────────────
# Connection management
# ─────────────────────────────────────────────

def _run_connector():
    global _is_running
    _is_running = True
    failures = 0

    while _is_running:
        if sio.connected:
            time.sleep(1)
            continue

        try:
            print(f"[DirectorBridge] Connecting to {DIRECTOR_URL}...")
            sio.connect(DIRECTOR_URL, transports=["websocket", "polling"], wait_timeout=10)
            failures = 0
            while _is_running and sio.connected:
                time.sleep(1)
        except socketio.exceptions.ConnectionError as e:
            failures += 1
            wait = min(5 * failures, 30)
            print(f"[DirectorBridge] Connection failed ({failures}): {e} — retry in {wait}s")
            for _ in range(wait * 2):
                if not _is_running:
                    return
                time.sleep(0.5)
        except Exception as e:
            print(f"[DirectorBridge] Unexpected error: {e}")
            time.sleep(5)


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def set_bot_reply_callback(cb: Callable):
    """Called whenever Director broadcasts a bot_reply event."""
    global _on_bot_reply_cb
    _on_bot_reply_cb = cb


def start():
    global _connector_thread
    _connector_thread = threading.Thread(
        target=_run_connector, daemon=True, name="DirectorBridge"
    )
    _connector_thread.start()


def stop():
    global _is_running
    _is_running = False
    if sio.connected:
        sio.disconnect()


def emit_twitch_message(username: str, message: str):
    """Emit a raw chat message event — Director uses this for UI display."""
    _safe_emit("twitch_message", {"username": username, "message": message})


def emit_scored_event(username: str, message: str, is_mention: bool):
    """
    Emit a scored input event so Director / Nami can decide whether to reply.
    """
    _safe_emit("event", {
        "source_str": "TWITCH_MENTION" if is_mention else "TWITCH_CHAT",
        "text": message,
        "metadata": {
            "username": username,
            "mentioned_bot": is_mention,
            "message_length": len(message),
            "relevance": 0.5,
        },
        "username": username,
    })


def _safe_emit(event: str, payload: dict):
    try:
        if sio.connected:
            sio.emit(event, payload)
        else:
            print(f"[DirectorBridge] ⚠️  Drop event '{event}' — not connected")
    except Exception as e:
        print(f"[DirectorBridge] ❌ Emit error for '{event}': {e}")