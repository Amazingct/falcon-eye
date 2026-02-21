"""
Falcon-Eye Agent Pod
Runs as a standalone pod handling all LLM interactions.
Receives chat requests from the API (dashboard) or directly from channels (Telegram/webhook).
Executes tools by calling back to the main API.
"""
import os
import asyncio
import json
import uuid
import logging
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, Request
from pydantic import BaseModel
import uvicorn

from tool_executor import execute_tool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("falcon-eye-agent")

AGENT_ID = os.getenv("AGENT_ID", "")
API_URL = os.getenv("API_URL", "http://falcon-eye-api:8000")
CHANNEL_TYPE = os.getenv("CHANNEL_TYPE", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "You are a Falcon-Eye AI agent.")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

MAX_TOOL_ITERATIONS = 8


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


# ─── Core LLM + Tool Loop ───────────────────────────────────

async def run_chat_loop(
    messages: list[dict],
    tools: list[dict],
    provider: str,
    model: str,
    api_key: str,
    base_url: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.7,
    agent_context: dict | None = None,
) -> tuple[str, int | None, int | None, list[dict]]:
    """Run the full LLM conversation loop with tool execution.

    Returns (response_text, prompt_tokens, completion_tokens, media_list).
    """
    total_prompt = 0
    total_completion = 0
    pending_media = []

    ctx = dict(agent_context or {})
    ctx["pending_media"] = pending_media

    if provider == "anthropic":
        return await _loop_anthropic(
            api_key, model, messages, tools, max_tokens, temperature, ctx
        )
    else:
        effective_base = base_url
        if not effective_base:
            effective_base = "http://ollama:11434/v1" if provider == "ollama" else "https://api.openai.com/v1"
        return await _loop_openai(
            api_key, model, effective_base, messages, tools, max_tokens, temperature, ctx
        )


async def _loop_openai(
    api_key: str, model: str, base_url: str,
    messages: list[dict], tools: list[dict],
    max_tokens: int, temperature: float,
    agent_context: dict,
) -> tuple[str, int | None, int | None, list[dict]]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    total_prompt = 0
    total_completion = 0

    for _ in range(MAX_TOOL_ITERATIONS):
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=120) as client:
            res = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
            if res.status_code != 200:
                raise Exception(f"LLM API error ({res.status_code}): {res.text[:500]}")
            data = res.json()

        choice = data["choices"][0]
        usage = data.get("usage", {})
        total_prompt += usage.get("prompt_tokens", 0)
        total_completion += usage.get("completion_tokens", 0)

        msg = choice["message"]

        if msg.get("tool_calls"):
            messages.append(msg)
            for tc in msg["tool_calls"]:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    fn_args = {}
                tool_result = await execute_tool(fn_name, fn_args, agent_context=agent_context)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_result,
                })
            continue

        return (
            msg.get("content", ""),
            total_prompt,
            total_completion,
            agent_context.get("pending_media", []),
        )

    return "Max tool iterations reached.", total_prompt, total_completion, agent_context.get("pending_media", [])


async def _loop_anthropic(
    api_key: str, model: str,
    messages: list[dict], tools: list[dict],
    max_tokens: int, temperature: float,
    agent_context: dict,
) -> tuple[str, int | None, int | None, list[dict]]:
    if not api_key:
        raise Exception("Anthropic API key not configured.")

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }

    system_prompt = None
    anthropic_messages = []
    for m in messages:
        if m["role"] == "system":
            system_prompt = m["content"]
        else:
            anthropic_messages.append({"role": m["role"], "content": m["content"]})

    anthropic_tools = []
    for t in tools:
        fn = t["function"]
        anthropic_tools.append({
            "name": fn["name"],
            "description": fn["description"],
            "input_schema": fn["parameters"],
        })

    total_prompt = 0
    total_completion = 0

    for _ in range(MAX_TOOL_ITERATIONS):
        payload = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            payload["system"] = system_prompt
        if anthropic_tools:
            payload["tools"] = anthropic_tools

        async with httpx.AsyncClient(timeout=120) as client:
            res = await client.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
            if res.status_code != 200:
                raise Exception(f"Anthropic API error ({res.status_code}): {res.text[:500]}")
            data = res.json()

        usage = data.get("usage", {})
        total_prompt += usage.get("input_tokens", 0)
        total_completion += usage.get("output_tokens", 0)

        tool_use_blocks = [b for b in data.get("content", []) if b["type"] == "tool_use"]
        text_blocks = [b for b in data.get("content", []) if b["type"] == "text"]

        if tool_use_blocks:
            anthropic_messages.append({"role": "assistant", "content": data["content"]})
            tool_results = []
            for tu in tool_use_blocks:
                result_text = await execute_tool(tu["name"], tu.get("input", {}), agent_context=agent_context)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": result_text,
                })
            anthropic_messages.append({"role": "user", "content": tool_results})
            continue

        response_text = " ".join(b["text"] for b in text_blocks) if text_blocks else ""
        return response_text, total_prompt, total_completion, agent_context.get("pending_media", [])

    return "Max tool iterations reached.", total_prompt, total_completion, agent_context.get("pending_media", [])


# ─── Helpers for self-initiated flows (Telegram/webhook) ────

_chat_config_cache: dict | None = None
_chat_config_ts: float = 0


async def fetch_chat_config() -> dict:
    """Fetch agent chat config (tools, system prompt, etc.) from the API.
    Cached for 60 seconds."""
    import time
    global _chat_config_cache, _chat_config_ts

    now = time.time()
    if _chat_config_cache and (now - _chat_config_ts) < 60:
        return _chat_config_cache

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(f"{API_URL}/api/agents/{AGENT_ID}/chat-config")
            if res.status_code == 200:
                _chat_config_cache = res.json()
                _chat_config_ts = now
                return _chat_config_cache
    except Exception as e:
        logger.error(f"Failed to fetch chat config: {e}")

    if _chat_config_cache:
        return _chat_config_cache
    return {}


async def fetch_history(session_id: str) -> list[dict]:
    """Fetch chat history from the API."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(
                f"{API_URL}/api/chat/{AGENT_ID}/history",
                params={"session_id": session_id, "limit": 50},
            )
            if res.status_code == 200:
                data = res.json()
                return [{"role": m["role"], "content": m["content"]} for m in data.get("messages", [])]
    except Exception as e:
        logger.error(f"Failed to fetch history: {e}")
    return []


async def save_message(session_id: str, role: str, content: str, source: str,
                       source_user: str | None = None,
                       prompt_tokens: int | None = None,
                       completion_tokens: int | None = None):
    """Save a message to the API database."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(
                f"{API_URL}/api/chat/{AGENT_ID}/messages/save",
                json={
                    "session_id": session_id,
                    "role": role,
                    "content": content,
                    "source": source,
                    "source_user": source_user,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                },
            )
    except Exception as e:
        logger.error(f"Failed to save message: {e}")


async def process_message(message_text: str, session_id: str, source: str = "telegram", source_user: str | None = None) -> dict:
    """Process a message from Telegram/webhook: fetch context, run LLM, save messages, return response."""
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

        # Build augmented system prompt
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

        agent_context = {
            "provider": provider,
            "model": model,
            "api_key": api_key,
        }

        await save_message(session_id, "user", message_text, source, source_user=source_user)

        response_text, prompt_tokens, completion_tokens, media = await run_chat_loop(
            messages=messages,
            tools=tools_schema,
            provider=provider,
            model=model,
            api_key=api_key,
            max_tokens=max_tokens,
            temperature=temperature,
            agent_context=agent_context,
        )

        await save_message(
            session_id, "assistant", response_text, source,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        )

        result = {"response": response_text}
        if media:
            result["media"] = media
        return result

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
            async with httpx.AsyncClient(timeout=10) as client:
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
        asyncio.ensure_future(persist_chat_id(chat_id))
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
    return {"status": status, "agent_id": AGENT_ID, "channel": CHANNEL_TYPE, "provider": LLM_PROVIDER}


@app.get("/")
async def root():
    return {"agent_id": AGENT_ID, "channel": CHANNEL_TYPE, "status": "running"}


@app.post("/chat/send")
async def chat_send(data: ChatSendRequest):
    """Handle a chat request from the API. Runs the full LLM + tool loop and returns the response.
    The API is responsible for message storage; this endpoint is a stateless LLM runner."""
    cfg = data.agent_config
    provider = cfg.get("provider", LLM_PROVIDER)
    model = cfg.get("model", LLM_MODEL)
    api_key = cfg.get("api_key", LLM_API_KEY)
    max_tokens = cfg.get("max_tokens", 4096)
    temperature = cfg.get("temperature", 0.7)

    agent_context = {
        "provider": provider,
        "model": model,
        "api_key": api_key,
    }

    try:
        response_text, prompt_tokens, completion_tokens, media = await run_chat_loop(
            messages=data.messages,
            tools=data.tools,
            provider=provider,
            model=model,
            api_key=api_key,
            max_tokens=max_tokens,
            temperature=temperature,
            agent_context=agent_context,
        )
    except Exception as e:
        logger.error(f"Chat loop error: {e}")
        return ChatSendResponse(response=f"Error: {e}", media=[])

    return ChatSendResponse(
        response=response_text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        media=media,
    )


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
