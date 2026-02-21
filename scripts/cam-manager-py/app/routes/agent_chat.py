"""Agent chat API routes"""
import asyncio
import json
import uuid
from collections import defaultdict
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, distinct
from pydantic import BaseModel

from app.database import get_db
from app.models.agent import Agent, AgentChatMessage
from app.tools.registry import TOOLS_REGISTRY, get_tools_for_agent
from app.tools.handlers import execute_tool

router = APIRouter(prefix="/api/chat", tags=["agent-chat"])

# Per-session locks: ensures messages within a session are processed one at a
# time so the AI always sees its own previous response before handling the next.
_session_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


class SendMessage(BaseModel):
    message: str
    session_id: Optional[str] = None
    source: str = "dashboard"
    source_user: Optional[str] = None


class SendResponse(BaseModel):
    response: str
    session_id: str
    timestamp: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None


@router.get("/{agent_id}/history")
async def get_chat_history(
    agent_id: UUID,
    session_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Get chat history for an agent"""
    query = select(AgentChatMessage).where(AgentChatMessage.agent_id == agent_id)
    if session_id:
        query = query.where(AgentChatMessage.session_id == session_id)
    query = query.order_by(AgentChatMessage.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    messages = result.scalars().all()
    return {"messages": [m.to_dict() for m in reversed(messages)]}


@router.post("/{agent_id}/send")
async def send_message(
    agent_id: UUID,
    data: SendMessage,
    db: AsyncSession = Depends(get_db),
):
    """Send a message to an agent and get LLM response.

    Uses a per-session lock so messages are processed sequentially — the AI
    always finishes responding before the next message is handled.
    """
    # Get agent
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    session_id = data.session_id or str(uuid.uuid4())
    lock_key = f"{agent_id}:{session_id}"

    async with _session_locks[lock_key]:
        # Store user message
        user_msg = AgentChatMessage(
            agent_id=agent_id,
            session_id=session_id,
            role="user",
            content=data.message,
            source=data.source,
            source_user=data.source_user,
        )
        db.add(user_msg)
        await db.flush()

        # Get tools for this agent
        agent_tools = agent.tools or []
        tools_schema = get_tools_for_agent(agent_tools) if agent_tools else []

        # Build messages for LLM
        llm_messages = []

        # System prompt — augment with tool awareness so the LLM reliably uses its tools
        system_prompt = agent.system_prompt or "You are a helpful AI assistant."
        if tools_schema:
            tool_lines = []
            for t in tools_schema:
                fn = t["function"]
                tool_lines.append(f"- **{fn['name']}**: {fn['description']}")
            system_prompt += (
                "\n\n## Available Tools\n"
                "You MUST use the appropriate tool when the user's request matches one. "
                "Do not describe what you would do — actually call the tool.\n\n"
                + "\n".join(tool_lines)
            )
        llm_messages.append({"role": "system", "content": system_prompt})

        # For pod agents, load history; for main agent, stateless
        if agent.slug != "main":
            history_result = await db.execute(
                select(AgentChatMessage)
                .where(AgentChatMessage.agent_id == agent_id, AgentChatMessage.session_id == session_id)
                .order_by(AgentChatMessage.created_at.asc())
            )
            history = history_result.scalars().all()
            for msg in history:
                llm_messages.append({"role": msg.role, "content": msg.content})
        else:
            # Stateless - just the current message
            llm_messages.append({"role": "user", "content": data.message})

        # Build agent context for tool handlers that need LLM creds (e.g. camera_analyze)
        import os
        resolved_key = agent.api_key_ref or ""
        if not resolved_key:
            if agent.provider == "anthropic":
                resolved_key = os.getenv("ANTHROPIC_API_KEY", "")
            elif agent.provider == "openai":
                resolved_key = os.getenv("OPENAI_API_KEY", "")

        agent_context = {
            "provider": agent.provider,
            "model": agent.model,
            "api_key": resolved_key,
            "pending_media": [],
        }

        # Call LLM
        try:
            response_text, prompt_tokens, completion_tokens = await _call_llm(
                agent, llm_messages, tools_schema, agent_context=agent_context
            )
        except Exception as e:
            response_text = f"Error: {str(e)}"
            prompt_tokens = None
            completion_tokens = None

        pending_media = agent_context.get("pending_media", [])

        # Store assistant response
        assistant_msg = AgentChatMessage(
            agent_id=agent_id,
            session_id=session_id,
            role="assistant",
            content=response_text,
            source=data.source,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        db.add(assistant_msg)
        await db.commit()

    # Clean up locks for sessions that are no longer active
    if not _session_locks[lock_key].locked():
        _session_locks.pop(lock_key, None)

    resp = {
        "response": response_text,
        "session_id": session_id,
        "timestamp": assistant_msg.created_at.isoformat() if assistant_msg.created_at else None,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
    if pending_media:
        resp["media"] = pending_media
    return resp


@router.get("/{agent_id}/sessions")
async def list_sessions(agent_id: UUID, db: AsyncSession = Depends(get_db)):
    """List chat sessions for an agent"""
    result = await db.execute(
        select(
            AgentChatMessage.session_id,
            func.min(AgentChatMessage.created_at).label("started_at"),
            func.max(AgentChatMessage.created_at).label("last_message_at"),
            func.count(AgentChatMessage.id).label("message_count"),
        )
        .where(AgentChatMessage.agent_id == agent_id)
        .group_by(AgentChatMessage.session_id)
        .order_by(func.max(AgentChatMessage.created_at).desc())
    )
    sessions = []
    for row in result:
        sessions.append({
            "session_id": row.session_id,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "last_message_at": row.last_message_at.isoformat() if row.last_message_at else None,
            "message_count": row.message_count,
        })
    return {"sessions": sessions}


@router.post("/{agent_id}/sessions/new")
async def create_session(agent_id: UUID, db: AsyncSession = Depends(get_db)):
    """Create a new chat session"""
    # Verify agent exists
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Agent not found")

    session_id = str(uuid.uuid4())
    return {"session_id": session_id}


async def _call_llm(agent: Agent, messages: list[dict], tools: list[dict], max_iterations: int = 5, agent_context: dict = None) -> tuple[str, int, int]:
    """Call the LLM provider with tool support.

    Key resolution order:
    1. Per-agent key from DB (agent.api_key_ref)
    2. Shared key from ConfigMap env (ANTHROPIC_API_KEY / OPENAI_API_KEY)
    """
    import os

    provider = agent.provider
    model = agent.model

    api_key = agent.api_key_ref or ""
    if not api_key:
        if provider == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY", "")
        elif provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY", "")

    if provider == "anthropic":
        return await _call_anthropic(api_key, model, messages, tools, agent.max_tokens, agent.temperature, max_iterations, agent_context=agent_context)
    elif provider in ("openai", "ollama"):
        base_url = "https://api.openai.com/v1" if provider == "openai" else "http://ollama:11434/v1"
        return await _call_openai_compatible(api_key, model, base_url, messages, tools, agent.max_tokens, agent.temperature, max_iterations, agent_context=agent_context)
    else:
        raise ValueError(f"Unsupported provider: {provider}")


async def _call_openai_compatible(api_key: str, model: str, base_url: str, messages: list, tools: list, max_tokens: int, temperature: float, max_iterations: int, agent_context: dict = None) -> tuple[str, int, int]:
    import httpx

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    total_prompt = 0
    total_completion = 0

    for _ in range(max_iterations):
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

        return msg.get("content", ""), total_prompt, total_completion

    return "Max tool iterations reached.", total_prompt, total_completion


async def _call_anthropic(api_key: str, model: str, messages: list, tools: list, max_tokens: int, temperature: float, max_iterations: int, agent_context: dict = None) -> tuple[str, int, int]:
    import httpx

    if not api_key:
        raise Exception("Anthropic API key not configured. Set it in the shared ConfigMap (ANTHROPIC_API_KEY) or per-agent in the dashboard.")

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }

    # Convert OpenAI format to Anthropic format
    system_prompt = None
    anthropic_messages = []
    for m in messages:
        if m["role"] == "system":
            system_prompt = m["content"]
        else:
            anthropic_messages.append({"role": m["role"], "content": m["content"]})

    # Convert tools to Anthropic format
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

    for _ in range(max_iterations):
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

        # Check for tool use
        tool_use_blocks = [b for b in data.get("content", []) if b["type"] == "tool_use"]
        text_blocks = [b for b in data.get("content", []) if b["type"] == "text"]

        if tool_use_blocks and data.get("stop_reason") == "tool_use":
            # Add assistant message with tool use
            anthropic_messages.append({"role": "assistant", "content": data["content"]})

            # Execute tools and add results
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

        # Extract text response
        response_text = " ".join(b["text"] for b in text_blocks) if text_blocks else ""
        return response_text, total_prompt, total_completion

    return "Max tool iterations reached.", total_prompt, total_completion
