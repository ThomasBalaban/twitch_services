# twitch_service/twitch_client.py
import asyncio
import threading
import time
from typing import Callable, Optional, Tuple

from twitchAPI.twitch import Twitch
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.type import AuthScope, ChatEvent
from twitchAPI.chat import Chat, EventData, ChatMessage

from config import APP_ID, APP_SECRET, TARGET_CHANNEL, BOT_NAME

USER_SCOPE = [AuthScope.CHAT_READ, AuthScope.CHAT_EDIT]

_chat: Optional[Chat] = None
_event_loop: Optional[asyncio.AbstractEventLoop] = None
_message_queue: Optional[asyncio.Queue] = None
_is_running = False
_auth_tokens: Optional[Tuple[str, str]] = None

_on_message_cb: Optional[Callable] = None


# ─────────────────────────────────────────────
# Step 1 — OAuth  (awaited directly in lifespan)
# ─────────────────────────────────────────────

async def authenticate() -> bool:
    """
    Await this from the FastAPI lifespan (which is already async).
    Opens the browser, waits for the user to click Authorize.
    Returns True on success.
    """
    global _auth_tokens
    print("[TwitchClient] 🔑 Starting Twitch OAuth — browser will open...")
    try:
        twitch = await Twitch(APP_ID, APP_SECRET)
        auth = UserAuthenticator(twitch, USER_SCOPE, force_verify=False)
        token, refresh_token = await auth.authenticate()
        await twitch.close()
        _auth_tokens = (token, refresh_token)
        print("[TwitchClient] ✅ OAuth complete")
        return True
    except Exception as e:
        print(f"[TwitchClient] ❌ OAuth failed: {e}")
        return False


# ─────────────────────────────────────────────
# Step 2 — Chat loop  (background daemon thread)
# ─────────────────────────────────────────────

def set_message_callback(cb: Callable):
    global _on_message_cb
    _on_message_cb = cb


async def _on_ready(ready_event: EventData):
    print(f"[TwitchClient] ✅ Bot ready — joining #{TARGET_CHANNEL}")
    await ready_event.chat.join_room(TARGET_CHANNEL)


async def _on_message(msg: ChatMessage):
    if msg.user.name.lower() == BOT_NAME.lower():
        return
    if _on_message_cb:
        await _on_message_cb(msg)


async def _sender_loop():
    global _message_queue
    while _is_running:
        try:
            message = await asyncio.wait_for(_message_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        if _chat:
            try:
                await _chat.send_message(TARGET_CHANNEL, message)
                print(f"[TwitchClient] 📤 Sent: {message[:80]}")
            except Exception as e:
                print(f"[TwitchClient] ❌ Send error: {e}")
        _message_queue.task_done()


async def _run():
    global _chat, _message_queue

    if not _auth_tokens:
        raise RuntimeError("authenticate() must be awaited before start()")

    token, refresh_token = _auth_tokens
    _message_queue = asyncio.Queue()

    twitch = await Twitch(APP_ID, APP_SECRET)
    await twitch.set_user_authentication(token, USER_SCOPE, refresh_token)
    print("[TwitchClient] 🔑 Re-authenticated with stored tokens")

    _chat = await Chat(twitch)
    _chat.register_event(ChatEvent.READY, _on_ready)
    _chat.register_event(ChatEvent.MESSAGE, _on_message)
    _chat.start()

    print(f"[TwitchClient] 💬 Chat client started for #{TARGET_CHANNEL}")
    await _sender_loop()


def _thread_target():
    global _event_loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _event_loop = loop
    loop.run_until_complete(_run())


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def start():
    """Start the chat loop in a background thread. authenticate() must have been awaited first."""
    global _is_running
    _is_running = True
    t = threading.Thread(target=_thread_target, daemon=True, name="TwitchClient")
    t.start()
    time.sleep(1)
    return t


def send_message(text: str):
    global _event_loop, _message_queue
    if _event_loop and _message_queue:
        asyncio.run_coroutine_threadsafe(_message_queue.put(text), _event_loop)
    else:
        print("[TwitchClient] ⚠️  Cannot send — client not ready yet")


def stop():
    global _is_running
    _is_running = False
    if _chat:
        _chat.stop()
    print("[TwitchClient] 🛑 Stopped")