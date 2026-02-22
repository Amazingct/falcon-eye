"""Agent chat API routes — proxies LLM calls to agent pods"""
import asyncio
import json
import os
import uuid
import logging
from collections import defaultdict
from typing import Optional, Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
import httpx

from app.database import get_db
from app.models.agent import Agent, AgentChatMessage, MEDIA_ROLES
from app.tools.registry import get_tools_for_agent
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["agent-chat"])
settings = get_settings()

_session_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

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
        timestamps = item.get("timestamps")
        cam = item.get("cam") if isinstance(item.get("cam"), dict) else None
        cam_part = ""
        if cam:
            cam_name = cam.get("name") or cam.get("cam_id")
            cam_loc = cam.get("location")
            cam_part = f" | cam={cam_name}" + (f" ({cam_loc})" if cam_loc else "")
        ts_part = f" | time={timestamps}" if timestamps else ""
        cap_part = f" | caption={caption}" if caption else ""
        nm_part = f"{name} " if name else ""
        lines.append(f"{i}. {nm_part}{mtype or 'file'} @ {path}{cam_part}{ts_part}{cap_part}")
    if len(media) > 20:
        lines.append(f"... {len(media) - 20} more item(s)")
    return "\n".join(lines)


def _coerce_role_for_llm(role: str) -> str:
    if role == "assistant_media":
        return "assistant"
    if role == "user_media":
        return "user"
    return role


def _coerce_content_for_llm(msg: AgentChatMessage) -> str:
    if msg.content_type == "media" or msg.role in MEDIA_ROLES:
        return _summarize_media_content(msg.content_media or {})
    return msg.content_text if msg.content_text is not None else (msg.content or "")


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


class SaveMessageRequest(BaseModel):
    session_id: str
    role: str
    content: Any
    source: str = "agent"
    source_user: Optional[str] = None
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
    """Send a message to an agent. Stores the user message, proxies to the
    agent pod for LLM processing, stores the response, and returns it."""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if not agent.service_name:
        raise HTTPException(
            status_code=503,
            detail="Agent pod is not deployed. Please start the agent first.",
        )

    session_id = data.session_id or str(uuid.uuid4())
    lock_key = f"{agent_id}:{session_id}"

    async with _session_locks[lock_key]:
        user_msg = AgentChatMessage(
            agent_id=agent_id,
            session_id=session_id,
            role="user",
            content=data.message,
            source=data.source,
            source_user=data.source_user,
        )
        user_msg.content_type = "text"
        user_msg.content_text = data.message
        user_msg.content_media = None
        db.add(user_msg)
        await db.flush()

        agent_tools = agent.tools or []
        tools_schema = get_tools_for_agent(agent_tools) if agent_tools else []

        # Build messages for the agent pod
        llm_messages = []

        system_prompt = agent.system_prompt or "You are a helpful AI assistant."
        if tools_schema:
            tool_lines = [f"- **{t['function']['name']}**: {t['function']['description']}" for t in tools_schema]
            system_prompt += (
                "\n\n## Available Tools\n"
                "You MUST use the appropriate tool when the user's request matches one. "
                "Do not describe what you would do — actually call the tool.\n\n"
                + "\n".join(tool_lines)
            )
        llm_messages.append({"role": "system", "content": system_prompt})

        history_result = await db.execute(
            select(AgentChatMessage)
            .where(AgentChatMessage.agent_id == agent_id, AgentChatMessage.session_id == session_id)
            .order_by(AgentChatMessage.created_at.asc())
        )
        history = history_result.scalars().all()
        for msg in history:
            llm_messages.append({
                "role": _coerce_role_for_llm(msg.role),
                "content": _coerce_content_for_llm(msg),
            })

        resolved_key = agent.api_key_ref or ""
        if not resolved_key:
            if agent.provider == "anthropic":
                resolved_key = os.getenv("ANTHROPIC_API_KEY", "")
            elif agent.provider == "openai":
                resolved_key = os.getenv("OPENAI_API_KEY", "")

        agent_config = {
            "provider": agent.provider,
            "model": agent.model,
            "api_key": resolved_key,
            "max_tokens": agent.max_tokens,
            "temperature": agent.temperature,
            "agent_id": str(agent_id),
            "session_id": session_id,
        }

        # Proxy to agent pod
        agent_url = f"http://{agent.service_name}.{settings.k8s_namespace}.svc.cluster.local:8080"
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                res = await client.post(
                    f"{agent_url}/chat/send",
                    json={
                        "messages": llm_messages,
                        "tools": tools_schema,
                        "agent_config": agent_config,
                    },
                )
                if res.status_code != 200:
                    raise Exception(f"Agent pod returned {res.status_code}: {res.text[:300]}")
                pod_response = res.json()
        except httpx.ConnectError:
            raise HTTPException(
                status_code=503,
                detail="Cannot reach agent pod. It may still be starting up. Please try again in a moment.",
            )
        except Exception as e:
            logger.error(f"Error proxying to agent pod: {e}")
            pod_response = {"response": f"Error communicating with agent pod: {e}"}

        response_text = pod_response.get("response", "")
        prompt_tokens = pod_response.get("prompt_tokens")
        completion_tokens = pod_response.get("completion_tokens")
        pending_media = pod_response.get("media", [])

        assistant_msg = AgentChatMessage(
            agent_id=agent_id,
            session_id=session_id,
            role="assistant",
            content=response_text,
            source=data.source,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        assistant_msg.content_type = "text"
        assistant_msg.content_text = response_text
        assistant_msg.content_media = None
        db.add(assistant_msg)

        # Save media messages to DB and resolve URLs
        if pending_media:
            for m in pending_media:
                # Add a URL the frontend can use
                if "path" in m and "url" not in m:
                    p = m["path"]
                    if p.startswith("/api/") or p.startswith("http"):
                        m["url"] = p
                    else:
                        m["url"] = f"/api/files/{p}"
                # Wrap in {media: [...]} format expected by ChatMedia component
                media_content = {"media": [m]}
                media_msg = AgentChatMessage(
                    agent_id=agent_id,
                    session_id=session_id,
                    role="assistant_media",
                    content=json.dumps(media_content),
                    source=data.source,
                )
                media_msg.content_type = "media"
                media_msg.content_text = m.get("caption", "")
                media_msg.content_media = media_content
                db.add(media_msg)

        await db.commit()

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
        # Wrap each item for ChatMedia format
        resp["media"] = [{"media": [m]} for m in pending_media]
    return resp


@router.post("/{agent_id}/messages/save")
async def save_message_endpoint(
    agent_id: UUID,
    data: SaveMessageRequest,
    db: AsyncSession = Depends(get_db),
):
    """Save a message directly. Used by agent pods handling Telegram/webhook
    messages to persist chat history without going through the send flow."""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    msg = AgentChatMessage(
        agent_id=agent_id,
        session_id=data.session_id,
        role=data.role,
        content="" if (data.role in MEDIA_ROLES and isinstance(data.content, dict)) else str(data.content),
        source=data.source,
        source_user=data.source_user,
        prompt_tokens=data.prompt_tokens,
        completion_tokens=data.completion_tokens,
    )
    # Populate typed content fields
    if data.role in MEDIA_ROLES:
        if not isinstance(data.content, dict):
            raise HTTPException(status_code=400, detail="content must be an object for media roles")
        msg.content_type = "media"
        msg.content_media = data.content
        msg.content_text = _summarize_media_content(data.content)
        # Keep legacy content column non-null
        msg.content = msg.content_text or ""
    else:
        msg.content_type = "text"
        msg.content_text = str(data.content)
        msg.content_media = None
    db.add(msg)
    await db.commit()
    return {"status": "saved"}


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
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Agent not found")

    session_id = str(uuid.uuid4())
    return {"session_id": session_id}
