# twitch_service/main.py
import re
import time
import uvicorn
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import twitch_client
import director_bridge
from config import SERVICE_PORT, TARGET_CHANNEL, BOT_NAME

_MENTION_RE = re.compile(r"(nami|peepingnami)", re.IGNORECASE)


def _strip_sound_effects(text: str) -> str:
    text = re.sub(r"\*[A-Za-z]+\*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text


def _handle_bot_reply(data: dict):
    reply = data.get("reply", "")
    if not reply:
        return
    chat_msg = "*censored*" if data.get("is_censored") else _strip_sound_effects(reply)
    if chat_msg:
        twitch_client.send_message(chat_msg)
        print(f"[Main] 📤 Forwarded bot_reply to Twitch: {chat_msg[:80]}")


async def _handle_twitch_message(msg):
    username = msg.user.name
    text = msg.text
    is_mention = bool(_MENTION_RE.search(text))
    director_bridge.emit_twitch_message(username, text)
    director_bridge.emit_scored_event(username, text, is_mention)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auth is a coroutine now — await it directly (no asyncio.run)
    ok = await twitch_client.authenticate()
    if not ok:
        print("[Main] ❌ Twitch auth failed — chat won't work")

    director_bridge.set_bot_reply_callback(_handle_bot_reply)
    twitch_client.set_message_callback(_handle_twitch_message)

    director_bridge.start()
    time.sleep(1)

    if ok:
        twitch_client.start()

    print(f"[Main] ✅ Twitch Service ready on :{SERVICE_PORT}")
    yield

    twitch_client.stop()
    director_bridge.stop()
    print("[Main] 🛑 Twitch Service stopped")


app = FastAPI(title="Nami Twitch Service", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "twitch_service", "port": SERVICE_PORT}


class SendMessagePayload(BaseModel):
    message: str
    username: Optional[str] = None


@app.post("/chat/send")
async def send_chat_message(payload: SendMessagePayload):
    msg = f"@{payload.username} {payload.message}" if payload.username else payload.message
    twitch_client.send_message(msg)
    return {"ok": True, "sent": msg}


class PollPayload(BaseModel):
    title: str
    choices: list[str]
    duration_seconds: int = 60


@app.post("/poll/create")
async def create_poll(payload: PollPayload):
    raise HTTPException(status_code=501, detail="Poll creation coming soon")


class PredictionPayload(BaseModel):
    title: str
    outcomes: list[str]
    prediction_window: int = 120


@app.post("/prediction/create")
async def create_prediction(payload: PredictionPayload):
    raise HTTPException(status_code=501, detail="Prediction creation coming soon")


class RedeemPayload(BaseModel):
    title: str
    cost: int
    is_enabled: bool = True


@app.post("/redeem/create")
async def create_redeem(payload: RedeemPayload):
    raise HTTPException(status_code=501, detail="Redeem creation coming soon")


if __name__ == "__main__":
    print("🎮 TWITCH SERVICE — Starting...")
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT, log_level="warning")