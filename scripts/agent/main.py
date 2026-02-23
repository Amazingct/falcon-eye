"""
Falcon-Eye Agent Pod — LangGraph-powered
Runs as a standalone pod using LangGraph's ReAct agent for all LLM interactions.
Receives chat requests from the API (dashboard) or directly from channels (Telegram/webhook).
Executes tools by calling back to the main API.
"""
import os
import asyncio
import uuid
import logging
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, Request
from pydantic import BaseModel
import uvicorn
from datetime import datetime

from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    AIMessage, HumanMessage, SystemMessage,
)
from langgraph.prebuilt import create_react_agent

from tool_executor import build_tools

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("falcon-eye-agent")

AGENT_ID = os.getenv("AGENT_ID", "")
API_URL = os.getenv("API_URL", "http://falcon-eye-api:8000")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

def _api_headers() -> dict:
    """Headers for internal API calls."""
    h = {}
    if INTERNAL_API_KEY:
        h["X-Internal-Key"] = INTERNAL_API_KEY
    return h
CHANNEL_TYPE = os.getenv("CHANNEL_TYPE", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4.1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "You are a Falcon-Eye AI agent.")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Task mode env vars — set when running as a K8s Job for a one-off task
AGENT_TASK = os.getenv("AGENT_TASK", "")
CALLER_AGENT_ID = os.getenv("CALLER_AGENT_ID", "")
CALLER_SESSION_ID = os.getenv("CALLER_SESSION_ID", "")

MAX_RECURSION = int(os.getenv("MAX_RECURSION", "50"))


# ─── Request / Response models ──────────────────────────────

class ChatSendRequest(BaseModel):
    messages: list[dict]
    tools: list[dict] = []
    agent_config: dict = {}


class ChatSendResponse(BaseModel):
    response: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    media: list[dict] = []


# ─── Model Factory ──────────────────────────────────────────

def get_llm(provider: str, model: str, api_key: str,
            temperature: float = 0.7, max_tokens: int = 4096,
            base_url: str = ""):
    if provider == "anthropic":
        return ChatAnthropic(
            model=model, api_key=api_key,
            temperature=temperature, max_tokens=max_tokens,
        )
    elif provider == "ollama":
        return ChatOpenAI(
            model=model,
            base_url=base_url or "http://ollama:11434/v1",
            api_key=api_key or "ollama",
            temperature=temperature, max_tokens=max_tokens,
        )
    else:
        kwargs: dict = {
            "model": model, "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOpenAI(**kwargs)


# ─── Core Chat Runner (LangGraph) ───────────────────────────

async def run_chat(
    messages: list[dict],
    tools_schema: list[dict],
    agent_config: dict,
) -> tuple[str, int | None, int | None, list[dict]]:
    """Run the LangGraph ReAct agent. Returns (response, prompt_tokens, completion_tokens, media)."""
    provider = agent_config.get("provider", LLM_PROVIDER)
    model_name = agent_config.get("model", LLM_MODEL)
    api_key = agent_config.get("api_key", LLM_API_KEY)
    temperature = agent_config.get("temperature", 0.7)
    max_tokens = agent_config.get("max_tokens", 4096)

    llm = get_llm(provider, model_name, api_key, temperature, max_tokens)

    agent_ctx = {
        "provider": provider, "model": model_name, "api_key": api_key,
        "agent_id": agent_config.get("agent_id", AGENT_ID),
        "session_id": agent_config.get("session_id"),
    }
    media_collector: list[dict] = []
    tools = build_tools(tools_schema, media_collector, API_URL, agent_ctx)

    # Convert dict messages to LangChain message objects
    lc_messages: list = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            lc_messages.append(SystemMessage(content=content))
        elif role == "assistant":
            lc_messages.append(AIMessage(content=content))
        else:
            lc_messages.append(HumanMessage(content=content))

    recursion_limit = agent_config.get("recursion_limit", MAX_RECURSION)
    agent = create_react_agent(model=llm, tools=tools)

    # Stream so we can capture partial results if the recursion limit is hit
    response_text = ""
    total_input = 0
    total_output = 0
    hit_limit = False

    try:
        async for step in agent.astream(
            {"messages": lc_messages},
            config={"recursion_limit": recursion_limit},
            stream_mode="updates",
        ):
            for _node_name, node_output in step.items():
                for msg in node_output.get("messages", []):
                    if isinstance(msg, AIMessage):
                        if msg.content and not msg.tool_calls:
                            response_text = msg.content
                        usage = getattr(msg, "usage_metadata", None)
                        if usage and isinstance(usage, dict):
                            total_input += usage.get("input_tokens", 0)
                            total_output += usage.get("output_tokens", 0)
    except Exception as e:
        if "recursion" in str(e).lower() or "GraphRecursionError" in type(e).__name__:
            hit_limit = True
            logger.warning("Hit recursion limit (%d). Returning last captured response.", recursion_limit)
            if not response_text:
                response_text = (
                    "(The task exceeded the maximum processing steps. "
                    "Partial progress was made but no final answer was produced.)"
                )
        else:
            raise

    return (
        response_text,
        total_input or None,
        total_output or None,
        media_collector,
    )


# ─── Helpers for self-initiated flows (Telegram/webhook) ────

_chat_config_cache: dict | None = None
_chat_config_ts: float = 0


async def fetch_chat_config() -> dict:
    """Fetch agent chat config (tools, system prompt, etc.) from the API. Cached for 60s."""
    import time
    global _chat_config_cache, _chat_config_ts

    now = time.time()
    if _chat_config_cache and (now - _chat_config_ts) < 60:
        return _chat_config_cache

    try:
        async with httpx.AsyncClient(timeout=15, headers=_api_headers()) as client:
            res = await client.get(f"{API_URL}/api/agents/{AGENT_ID}/chat-config")
            if res.status_code == 200:
                _chat_config_cache = res.json()
                _chat_config_ts = now
                return _chat_config_cache
    except Exception as e:
        logger.error(f"Failed to fetch chat config: {e}")

    return _chat_config_cache or {}


async def fetch_history(session_id: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=15, headers=_api_headers()) as client:
            res = await client.get(
                f"{API_URL}/api/chat/{AGENT_ID}/history",
                params={"session_id": session_id, "limit": 50},
            )
            if res.status_code == 200:
                data = res.json()
                return [_coerce_history_message_for_llm(m) for m in data.get("messages", [])]
    except Exception as e:
        logger.error(f"Failed to fetch history: {e}")
    return []


def _summarize_media_content(content: dict) -> str:
    """Convert structured media payload into a short text summary for LLM context."""
    if not isinstance(content, dict):
        return "(media)"
    lines: list[str] = []
    general = content.get("general_caption")
    if general:
        lines.append(f"Media caption: {general}")
    media = content.get("media") or []
    if not isinstance(media, list) or not media:
        lines.append("Media: (no items)")
        return "\n".join(lines)
    lines.append(f"Media items: {len(media)}")
    for i, item in enumerate(media[:20], start=1):
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        mtype = item.get("type")
        path = item.get("path")
        caption = item.get("caption")
        nm_part = f"{name} " if name else ""
        cap_part = f" | caption={caption}" if caption else ""
        lines.append(f"{i}. {nm_part}{mtype or 'file'} @ {path}{cap_part}")
    if len(media) > 20:
        lines.append(f"... {len(media) - 20} more item(s)")
    return "\n".join(lines)


def _coerce_role_for_llm(role: str) -> str:
    if role == "assistant_media":
        return "assistant"
    if role == "user_media":
        return "user"
    return role


def _coerce_history_message_for_llm(m: dict) -> dict:
    role = _coerce_role_for_llm(m.get("role", "user"))
    content = m.get("content", "")
    if isinstance(content, dict) or m.get("role") in ("assistant_media", "user_media"):
        content = _summarize_media_content(content if isinstance(content, dict) else {})
    elif content is None:
        content = ""
    elif not isinstance(content, str):
        content = str(content)
    return {"role": role, "content": content}


async def save_message(session_id: str, role: str, content, source: str,
                       source_user: str | None = None,
                       prompt_tokens: int | None = None,
                       completion_tokens: int | None = None):
    try:
        async with httpx.AsyncClient(timeout=15, headers=_api_headers()) as client:
            res = await client.post(
                f"{API_URL}/api/chat/{AGENT_ID}/messages/save",
                json={
                    "session_id": session_id, "role": role,
                    "content": content, "source": source,
                    "source_user": source_user,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                },
            )
            if res.status_code >= 400:
                logger.error("Failed to save message (HTTP %d): %s", res.status_code, res.text[:300])
    except Exception as e:
        logger.error(f"Failed to save message: {e}")


async def process_message(message_text: str, session_id: str,
                          source: str = "telegram",
                          source_user: str | None = None) -> dict:
    """Process a message from Telegram/webhook using LangGraph agent."""
    try:
        config = await fetch_chat_config()
        if not config:
            return {"response": "Agent not configured yet. Please try again later."}

        provider = config.get("provider", LLM_PROVIDER)
        model = config.get("model", LLM_MODEL)
        api_key = config.get("api_key", LLM_API_KEY)
        system_prompt = config.get("system_prompt", SYSTEM_PROMPT)
        tools_schema = config.get("tools_schema", [])
        max_tokens = config.get("max_tokens", 4096)
        temperature = config.get("temperature", 0.7)

        if tools_schema:
            tool_lines = [f"- **{t['function']['name']}**: {t['function']['description']}" for t in tools_schema]
            system_prompt += (
                "\n\n## Available Tools\n"
                "You MUST use the appropriate tool when the user's request matches one. "
                "Do not describe what you would do — actually call the tool.\n\n"
                + "\n".join(tool_lines)
            )

        history = await fetch_history(session_id)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        if not history or history[-1].get("content") != message_text:
            messages.append({"role": "user", "content": message_text})

        await save_message(session_id, "user", message_text, source, source_user=source_user)

        agent_config = {
            "provider": provider, "model": model, "api_key": api_key,
            "max_tokens": max_tokens, "temperature": temperature,
            "agent_id": AGENT_ID, "session_id": session_id,
        }

        response_text, prompt_tokens, completion_tokens, media = await run_chat(
            messages=messages, tools_schema=tools_schema, agent_config=agent_config,
        )

        await save_message(
            session_id, "assistant", response_text, source,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        )

        # Save media messages to DB (skip items already persisted by deliver_media_message)
        unsaved_media = [m for m in media if not m.get("_already_persisted")] if media else []
        if unsaved_media:
            media_payload = {
                "general_caption": None,
                "media": [
                    {
                        "name": os.path.basename(m.get("path", "") or ""),
                        "path": m.get("path", ""),
                        "cloud_url": m.get("cloud_url"),
                        "url": m.get("url"),
                        "caption": m.get("caption", ""),
                        "type": os.path.splitext(m.get("path", ""))[1].lstrip(".") or m.get("media_type", "file"),
                        "cam": None,
                        "timestamps": None,
                    }
                    for m in unsaved_media
                ],
            }
            await save_message(session_id, "assistant_media", media_payload, source)

        result: dict = {"response": response_text, "session_id": session_id}
        if media:
            result["media"] = media
        return result

    except Exception as e:
        logger.error(f"Error processing message: {e}")
        return {"response": f"Error: {e}"}


async def download_file(path: str) -> bytes | None:
    try:
        # Determine the full URL based on path type
        if path.startswith("http://") or path.startswith("https://"):
            url = path  # Full URL (e.g. cloud URL)
        elif path.startswith("/api/"):
            url = f"{API_URL}{path}"  # API path (e.g. /api/recordings/{id}/download)
        else:
            url = f"{API_URL}/api/files/read/{path}"  # Filesystem path

        async with httpx.AsyncClient(timeout=60, headers=_api_headers()) as client:
            res = await client.get(url)
            if res.status_code == 200:
                content_type = res.headers.get("content-type", "")
                if "application/json" in content_type:
                    data = res.json()
                    return data.get("content", "").encode("utf-8") if "content" in data else None
                return res.content
            else:
                logger.error(f"Failed to download {url}: {res.status_code}")
    except Exception as e:
        logger.error(f"Failed to download file {path}: {e}")
    return None


async def upload_file(path: str, file_bytes: bytes, filename: str, mime_type: str = "application/octet-stream") -> bool:
    """Upload binary content into the shared filesystem via the API."""
    try:
        async with httpx.AsyncClient(timeout=60, headers=_api_headers()) as client:
            res = await client.post(
                f"{API_URL}/api/files/upload/{path}",
                files={"file": (filename, file_bytes, mime_type)},
            )
            return res.status_code == 200
    except Exception as e:
        logger.error(f"Failed to upload file {path}: {e}")
        return False


# ─── Telegram Bot ───────────────────────────────────────────

telegram_app = None
telegram_ready = False


async def start_telegram_bot():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set, cannot start Telegram bot")
        return

    from telegram import Update
    from telegram.ext import Application, MessageHandler, CommandHandler, filters

    chat_sessions: dict[int, str] = {}
    chat_id_persisted = False

    async def persist_chat_id(chat_id: int):
        nonlocal chat_id_persisted
        if chat_id_persisted:
            return
        try:
            async with httpx.AsyncClient(timeout=10, headers=_api_headers()) as client:
                res = await client.get(f"{API_URL}/api/agents/{AGENT_ID}")
                if res.status_code == 200:
                    agent_data = res.json()
                    cfg = agent_data.get("channel_config") or {}
                    if cfg.get("chat_id") == chat_id:
                        chat_id_persisted = True
                        return
                    cfg["chat_id"] = chat_id
                    await client.patch(
                        f"{API_URL}/api/agents/{AGENT_ID}",
                        json={"channel_config": cfg},
                    )
                    chat_id_persisted = True
                    logger.info(f"Persisted Telegram chat_id={chat_id}")
        except Exception as e:
            logger.warning(f"Failed to persist chat_id: {e}")

    async def send_media_to_chat(chat, media_item, bot):
        # Prioritize: url > cloud_url > path
        file_path = media_item.get("url") or media_item.get("cloud_url") or media_item.get("path", "")
        caption = media_item.get("caption", "")
        media_type = media_item.get("media_type", "document")

        file_bytes = await download_file(file_path)
        if not file_bytes:
            await chat.send_message(f"(could not download: {file_path})")
            return

        # Sanity check: if we got a tiny response that looks like JSON error, don't send it as media
        if len(file_bytes) < 500:
            try:
                import json as _json
                _json.loads(file_bytes)
                # It's JSON — likely an error response, not actual media
                logger.error(f"Got JSON error instead of media file from {file_path}: {file_bytes[:200]}")
                await chat.send_message(f"(download returned an error for: {os.path.basename(file_path)})")
                return
            except (ValueError, UnicodeDecodeError):
                pass  # Not JSON, proceed normally

        import io
        buf = io.BytesIO(file_bytes)
        buf.name = os.path.basename(file_path) or "download"
        # Ensure filename has an extension for Telegram to handle it properly
        if "." not in buf.name:
            ext_map = {"photo": ".jpg", "video": ".mp4", "document": ""}
            buf.name += ext_map.get(media_type, "")

        try:
            if media_type == "photo":
                await bot.send_photo(chat_id=chat.id, photo=buf, caption=caption or None)
            elif media_type == "video":
                await bot.send_video(chat_id=chat.id, video=buf, caption=caption or None)
            else:
                await bot.send_document(chat_id=chat.id, document=buf, caption=caption or None)
        except Exception as e:
            logger.error(f"Failed to send media {file_path}: {e}")
            await chat.send_message(f"(failed to send {os.path.basename(file_path)}: {e})")

    async def handle_message(update: Update, context):
        if not update.message:
            return
        chat_id = update.effective_chat.id
        user = update.effective_user
        source_user = user.username or user.first_name if user else str(chat_id)
        if chat_id not in chat_sessions:
            chat_sessions[chat_id] = str(uuid.uuid4())
        session_id = chat_sessions[chat_id]
        asyncio.ensure_future(persist_chat_id(chat_id))

        # 1) Text messages (existing path)
        if update.message.text:
            await update.message.chat.send_action("typing")
            result = await process_message(
                update.message.text, session_id=session_id,
                source="telegram", source_user=source_user,
            )
            response_text = result.get("response", "")
            media_items = result.get("media", [])
            if response_text:
                for i in range(0, len(response_text), 4000):
                    await update.message.reply_text(response_text[i:i + 4000])
            for item in media_items:
                await send_media_to_chat(update.effective_chat, item, context.bot)
            return

        # 2) Attachments -> user_media
        attachment = None
        filename = None
        mime_type = "application/octet-stream"

        if update.message.photo:
            attachment = update.message.photo[-1]
            filename = f"photo_{attachment.file_id}.jpg"
            mime_type = "image/jpeg"
        elif update.message.video:
            attachment = update.message.video
            filename = getattr(attachment, "file_name", None) or f"video_{attachment.file_id}.mp4"
            mime_type = getattr(attachment, "mime_type", None) or "video/mp4"
        elif update.message.audio:
            attachment = update.message.audio
            filename = getattr(attachment, "file_name", None) or f"audio_{attachment.file_id}.mp3"
            mime_type = getattr(attachment, "mime_type", None) or "audio/mpeg"
        elif update.message.document:
            attachment = update.message.document
            filename = getattr(attachment, "file_name", None) or f"file_{attachment.file_id}"
            mime_type = getattr(attachment, "mime_type", None) or "application/octet-stream"

        if not attachment:
            return

        try:
            tg_file = await context.bot.get_file(attachment.file_id)
            file_bytes = await tg_file.download_as_bytearray()
        except Exception as e:
            logger.error(f"Failed to download Telegram attachment: {e}")
            await update.message.reply_text("(Failed to download attachment.)")
            return

        # Store under shared filesystem
        safe_name = "".join(c if c.isalnum() or c in ("-", "_", ".", " ") else "_" for c in (filename or "file"))
        safe_name = safe_name.strip().replace(" ", "_")[:120] or "file"
        dest_path = f"uploads/telegram/{session_id}/{uuid.uuid4().hex[:8]}_{safe_name}"
        ok = await upload_file(dest_path, bytes(file_bytes), safe_name, mime_type=mime_type)
        if not ok:
            await update.message.reply_text("(Failed to upload attachment to server.)")
            return

        ext = os.path.splitext(safe_name)[1].lower().lstrip(".") or "bin"
        caption = update.message.caption if getattr(update.message, "caption", None) else None
        user_media_payload = {
            "general_caption": caption,
            "media": [
                {
                    "name": safe_name,
                    "cam": None,
                    "timestamps": datetime.utcnow().isoformat() + "Z",
                    "caption": caption,
                    "path": dest_path,
                    "type": ext,
                }
            ],
        }

        await save_message(session_id, "user_media", user_media_payload, "telegram", source_user=source_user)

        # Optional: trigger an AI reply using caption or a short summary
        prompt = caption or f"I sent you an attachment: {safe_name} ({ext})"
        await update.message.chat.send_action("typing")
        result = await process_message(prompt, session_id=session_id, source="telegram", source_user=source_user)
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
        asyncio.ensure_future(persist_chat_id(chat_id))
        await update.message.reply_text("Hello! I'm your Falcon-Eye agent. How can I help?")

    async def handle_new_session(update: Update, context):
        chat_id = update.effective_chat.id
        chat_sessions[chat_id] = str(uuid.uuid4())
        await update.message.reply_text("Started a new session.")

    global telegram_app
    telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", handle_start))
    telegram_app.add_handler(CommandHandler("new", handle_new_session))
    # Handle both text and attachments (photos/videos/documents/audio)
    telegram_app.add_handler(MessageHandler(~filters.COMMAND, handle_message))

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
            logger.warning(f"Telegram init attempt {attempt}/{max_retries} failed, retrying in {wait}s...")
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


# ─── FastAPI Server ─────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
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
    return {
        "status": status, "agent_id": AGENT_ID,
        "channel": CHANNEL_TYPE, "provider": LLM_PROVIDER,
    }


@app.get("/")
async def root():
    return {"agent_id": AGENT_ID, "channel": CHANNEL_TYPE, "status": "running"}


@app.post("/chat/send")
async def chat_send(data: ChatSendRequest):
    """Stateless LLM runner. Receives messages + tools + config, returns response."""
    cfg = data.agent_config

    try:
        response_text, prompt_tokens, completion_tokens, media = await run_chat(
            messages=data.messages,
            tools_schema=data.tools,
            agent_config=cfg,
        )
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return ChatSendResponse(response=f"Error: {e}", media=[])

    return ChatSendResponse(
        response=response_text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        media=media,
    )


@app.post("/webhook")
async def webhook_handler(request: Request):
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


# ─── Task Mode (K8s Job — run once, callback, exit) ─────────

async def run_task_mode():
    """Execute a single task from AGENT_TASK env var, post result to callback, then exit."""
    logger.info("Task mode: agent=%s task_length=%d", AGENT_ID, len(AGENT_TASK))

    # Wait for API to become reachable
    for attempt in range(30):
        try:
            async with httpx.AsyncClient(timeout=5, headers=_api_headers()) as client:
                res = await client.get(f"{API_URL}/health")
                if res.status_code == 200:
                    break
        except Exception:
            pass
        await asyncio.sleep(2)
    else:
        logger.error("API unreachable after 60s, aborting task")
        await _post_task_complete("(Agent could not reach the API)")
        return

    # Fetch chat config (tools, system prompt, api key)
    config = None
    for attempt in range(10):
        try:
            async with httpx.AsyncClient(timeout=15, headers=_api_headers()) as client:
                res = await client.get(f"{API_URL}/api/agents/{AGENT_ID}/chat-config")
                if res.status_code == 200:
                    config = res.json()
                    break
        except Exception:
            pass
        await asyncio.sleep(3)

    if not config:
        logger.error("Failed to fetch chat config")
        await _post_task_complete("(Failed to fetch agent configuration)")
        return

    tools_schema = config.get("tools_schema", [])
    system_prompt = config.get("system_prompt", SYSTEM_PROMPT)

    if tools_schema:
        tool_lines = [
            f"- **{t['function']['name']}**: {t['function']['description']}"
            for t in tools_schema
        ]
        system_prompt += (
            "\n\n## Available Tools\n"
            "You MUST use the appropriate tool when the user's request matches one. "
            "Do not describe what you would do — actually call the tool.\n\n"
            + "\n".join(tool_lines)
        )

    # Task-mode agents should be efficient to avoid hitting the recursion limit
    system_prompt += (
        "\n\n## Task Execution Guidelines\n"
        "You are running as a single-task agent. Be efficient:\n"
        "- Limit web searches to 3-5 queries. Do NOT repeat similar searches.\n"
        "- Once you have sufficient information, stop searching and produce your answer.\n"
        "- If you need to write a file, gather ALL information first, then write ONCE.\n"
        "- Produce a complete, well-structured final answer when done.\n"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": AGENT_TASK},
    ]

    agent_config = {
        "provider": config.get("provider", LLM_PROVIDER),
        "model": config.get("model", LLM_MODEL),
        "api_key": config.get("api_key", LLM_API_KEY),
        "max_tokens": config.get("max_tokens", 4096),
        "temperature": config.get("temperature", 0.7),
        "agent_id": AGENT_ID,
    }

    try:
        response_text, _, _, _ = await run_chat(
            messages=messages, tools_schema=tools_schema, agent_config=agent_config,
        )
    except Exception as e:
        logger.error("Task execution failed: %s", e)
        response_text = f"(Task execution failed: {e})"

    await _post_task_complete(response_text)
    logger.info("Task mode complete, exiting.")


async def _post_task_complete(result: str):
    """Post task result back to the API's task-complete callback endpoint."""
    try:
        async with httpx.AsyncClient(timeout=30, headers=_api_headers()) as client:
            await client.post(
                f"{API_URL}/api/agents/{AGENT_ID}/task-complete",
                json={
                    "result": result,
                    "caller_agent_id": CALLER_AGENT_ID,
                    "caller_session_id": CALLER_SESSION_ID,
                },
            )
    except Exception as e:
        logger.error("Failed to post task completion: %s", e)


if __name__ == "__main__":
    if AGENT_TASK:
        asyncio.run(run_task_mode())
    else:
        uvicorn.run(app, host="0.0.0.0", port=8080)
