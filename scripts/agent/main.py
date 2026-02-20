"""
Falcon-Eye Agent Pod
Runs as a standalone pod, connects to LLM and optional channel (Telegram/webhook).
"""
import os
import asyncio
import json
import uuid
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
import uvicorn

from llm_client import chat as llm_chat
from tool_executor import execute_tool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("falcon-eye-agent")

# Configuration from environment
AGENT_ID = os.getenv("AGENT_ID", "")
API_URL = os.getenv("API_URL", "http://falcon-eye-api:8000")
CHANNEL_TYPE = os.getenv("CHANNEL_TYPE", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "You are a Falcon-Eye AI agent.")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

MAX_TOOL_ITERATIONS = 5


async def get_chat_history(agent_id: str, session_id: str) -> list[dict]:
    """Fetch chat history from main API"""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(f"{API_URL}/api/chat/{agent_id}/history", params={"session_id": session_id, "limit": 50})
            if res.status_code == 200:
                data = res.json()
                return [{"role": m["role"], "content": m["content"]} for m in data.get("messages", [])]
    except Exception as e:
        logger.error(f"Failed to fetch history: {e}")
    return []


async def save_message(agent_id: str, session_id: str, role: str, content: str, source: str, source_user: str = None, prompt_tokens: int = None, completion_tokens: int = None):
    """Save a message to the main API"""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Use the direct chat history endpoint (POST message to send, but we need raw save)
            # For now, we'll POST to send which handles storage
            pass
    except Exception as e:
        logger.error(f"Failed to save message: {e}")


async def process_message(message_text: str, session_id: str, source: str = "telegram", source_user: str = None) -> dict:
    """Process an incoming message through the LLM with tool support.

    Returns dict with 'response' (text) and optional 'media' (list of files to send).
    """
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            res = await client.post(
                f"{API_URL}/api/chat/{AGENT_ID}/send",
                json={
                    "message": message_text,
                    "session_id": session_id,
                    "source": source,
                    "source_user": source_user,
                },
            )
            if res.status_code == 200:
                return res.json()
            else:
                return {"response": f"Error from API ({res.status_code}): {res.text[:200]}"}
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        return {"response": f"Error: {e}"}


async def download_file(path: str) -> bytes | None:
    """Download a file from the shared filesystem via the main API."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.get(f"{API_URL}/api/files/read/{path}")
            if res.status_code == 200:
                content_type = res.headers.get("content-type", "")
                if "application/json" in content_type:
                    data = res.json()
                    return data.get("content", "").encode("utf-8") if "content" in data else None
                return res.content
    except Exception as e:
        logger.error(f"Failed to download file {path}: {e}")
    return None


# ─── Telegram Bot ───────────────────────────────────────────

telegram_app = None
telegram_ready = False


async def start_telegram_bot():
    """Start Telegram bot polling"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set, cannot start Telegram bot")
        return

    from telegram import Update
    from telegram.ext import Application, MessageHandler, CommandHandler, filters

    # Track sessions per chat
    chat_sessions: dict[int, str] = {}

    async def send_media_to_chat(chat, media_item, bot):
        """Download a file from the API and send it via Telegram."""
        file_path = media_item.get("path", "")
        caption = media_item.get("caption", "")
        media_type = media_item.get("media_type", "document")

        file_bytes = await download_file(file_path)
        if not file_bytes:
            await chat.send_message(f"(could not download: {file_path})")
            return

        filename = os.path.basename(file_path)
        import io
        buf = io.BytesIO(file_bytes)
        buf.name = filename

        try:
            if media_type == "photo":
                await bot.send_photo(chat_id=chat.id, photo=buf, caption=caption or None)
            elif media_type == "video":
                await bot.send_video(chat_id=chat.id, video=buf, caption=caption or None)
            else:
                await bot.send_document(chat_id=chat.id, document=buf, caption=caption or None)
        except Exception as e:
            logger.error(f"Failed to send media {file_path}: {e}")
            await chat.send_message(f"(failed to send {filename}: {e})")

    async def handle_message(update: Update, context):
        if not update.message or not update.message.text:
            return

        chat_id = update.effective_chat.id
        user = update.effective_user
        source_user = user.username or user.first_name if user else str(chat_id)

        if chat_id not in chat_sessions:
            chat_sessions[chat_id] = str(uuid.uuid4())

        session_id = chat_sessions[chat_id]

        await update.message.chat.send_action("typing")

        result = await process_message(
            update.message.text,
            session_id=session_id,
            source="telegram",
            source_user=source_user,
        )

        response_text = result.get("response", "")
        media_items = result.get("media", [])

        if response_text:
            for i in range(0, len(response_text), 4000):
                await update.message.reply_text(response_text[i:i + 4000])

        for item in media_items:
            await send_media_to_chat(update.effective_chat, item, context.bot)

    async def handle_start(update: Update, context):
        chat_id = update.effective_chat.id
        chat_sessions[chat_id] = str(uuid.uuid4())
        await update.message.reply_text("🦅 Hello! I'm your Falcon-Eye agent. How can I help?")

    async def handle_new_session(update: Update, context):
        chat_id = update.effective_chat.id
        chat_sessions[chat_id] = str(uuid.uuid4())
        await update.message.reply_text("✨ Started a new session.")

    global telegram_app
    telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", handle_start))
    telegram_app.add_handler(CommandHandler("new", handle_new_session))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Starting Telegram bot polling...")
    max_retries = 10
    for attempt in range(1, max_retries + 1):
        try:
            await telegram_app.initialize()
            break
        except Exception as e:
            if attempt == max_retries:
                logger.error(f"Failed to initialize Telegram bot after {max_retries} attempts: {e}")
                return
            wait = min(2 ** attempt, 30)
            logger.warning(f"Telegram bot init attempt {attempt}/{max_retries} failed ({e.__class__.__name__}), retrying in {wait}s...")
            await asyncio.sleep(wait)

    global telegram_ready
    await telegram_app.start()
    await telegram_app.updater.start_polling(drop_pending_updates=True)
    telegram_ready = True
    logger.info("Telegram bot polling started successfully")


async def stop_telegram_bot():
    global telegram_app
    if telegram_app:
        await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()


# ─── FastAPI Health + Webhook Server ────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start channel on startup, cleanup on shutdown"""
    if CHANNEL_TYPE == "telegram":
        asyncio.create_task(start_telegram_bot())
    yield
    if CHANNEL_TYPE == "telegram":
        await stop_telegram_bot()


app = FastAPI(title="Falcon-Eye Agent", lifespan=lifespan)


@app.get("/health")
async def health():
    status = "ok"
    if CHANNEL_TYPE == "telegram" and not telegram_ready:
        status = "degraded"
    return {"status": status, "agent_id": AGENT_ID, "channel": CHANNEL_TYPE, "provider": LLM_PROVIDER}


@app.get("/")
async def root():
    return {"agent_id": AGENT_ID, "channel": CHANNEL_TYPE, "status": "running"}


# Webhook endpoint for webhook-type agents
@app.post("/webhook")
async def webhook_handler(request: Request):
    """Handle incoming webhook messages"""
    if CHANNEL_TYPE != "webhook":
        return {"error": "Agent is not configured for webhook mode"}

    body = await request.json()
    message = body.get("message", "")
    session_id = body.get("session_id", str(uuid.uuid4()))
    source = body.get("source", "webhook")
    source_user = body.get("source_user")

    if not message:
        return {"error": "No message provided"}

    result = await process_message(message, session_id=session_id, source=source, source_user=source_user)
    return {"response": result.get("response", ""), "session_id": session_id, "media": result.get("media", [])}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
