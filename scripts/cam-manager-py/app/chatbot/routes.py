"""
Chatbot API routes with SSE streaming and session management
"""
import json
import asyncio
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update
from datetime import datetime

from app.chatbot.graph import stream_chat, create_graph
from app.database import get_db
from app.models.chat import ChatSession, ChatMessage, MEDIA_ROLES

router = APIRouter(prefix="/api/chat", tags=["chatbot"])

def _summarize_media_content(content: dict) -> str:
    if not isinstance(content, dict):
        return "(media)"
    general = content.get("general_caption")
    media = content.get("media") or []
    parts: list[str] = []
    if general:
        parts.append(f"Media caption: {general}")
    if isinstance(media, list) and media:
        parts.append(f"Media items: {len(media)}")
        for i, item in enumerate(media[:20], start=1):
            if not isinstance(item, dict):
                continue
            parts.append(f"{i}. {item.get('type','file')} @ {item.get('path')}")
    else:
        parts.append("Media: (no items)")
    return "\n".join(parts)


def _coerce_role_for_llm(role: str) -> str:
    if role == "assistant_media":
        return "assistant"
    if role == "user_media":
        return "user"
    return role


def _coerce_content_for_llm(msg: ChatMessage) -> str:
    if msg.content_type == "media" or msg.role in MEDIA_ROLES:
        return _summarize_media_content(msg.content_media or {})
    return msg.content_text if msg.content_text is not None else (msg.content or "")


class Message(BaseModel):
    """Chat message"""
    role: str  # user | assistant
    content: str


class ChatRequest(BaseModel):
    """Chat request body"""
    messages: list[Message]
    stream: bool = True


class ChatResponse(BaseModel):
    """Non-streaming chat response"""
    message: Message
    

@router.post("/")
async def chat(request: ChatRequest):
    """
    Chat endpoint with optional streaming.
    
    If stream=True (default), returns SSE stream.
    If stream=False, returns complete response.
    """
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages provided")
    
    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    
    if request.stream:
        return EventSourceResponse(
            stream_response(messages),
            media_type="text/event-stream"
        )
    else:
        # Non-streaming response
        full_response = ""
        async for event_type, data in stream_chat(messages):
            if event_type == "text":
                full_response += data
        
        return ChatResponse(
            message=Message(role="assistant", content=full_response)
        )


async def stream_response(messages: list[dict]):
    """Generator for SSE streaming"""
    try:
        async for event_type, data in stream_chat(messages):
            if event_type == "text":
                yield {
                    "event": "message",
                    "data": json.dumps({"content": data})
                }
            elif event_type == "thinking":
                yield {
                    "event": "thinking",
                    "data": json.dumps({"status": "using_tools"})
                }
        
        # Send done event
        yield {
            "event": "done",
            "data": json.dumps({"status": "complete"})
        }
        
    except ValueError as e:
        # API key not set
        yield {
            "event": "error",
            "data": json.dumps({"error": "Chatbot not configured. Please add your Anthropic API key in Settings."})
        }
    except Exception as e:
        error_str = str(e)
        # Parse common error types for user-friendly messages
        if "401" in error_str or "authentication_error" in error_str or "invalid x-api-key" in error_str.lower():
            user_error = "Invalid Anthropic API key. Please check your API key in Settings."
        elif "rate_limit" in error_str.lower() or "429" in error_str:
            user_error = "Rate limit exceeded. Please wait a moment and try again."
        else:
            user_error = f"Chat error: {error_str}"
        
        yield {
            "event": "error", 
            "data": json.dumps({"error": user_error})
        }


@router.get("/health")
async def chat_health():
    """Check if chatbot is configured"""
    import os
    api_key = os.getenv("ANTHROPIC_API_KEY")
    
    return {
        "status": "ok" if api_key else "unconfigured",
        "configured": bool(api_key),
        "model": "claude-sonnet-4-20250514",
    }


# ============ Session Management ============

class SessionCreate(BaseModel):
    """Create session request"""
    name: Optional[str] = None


class SessionUpdate(BaseModel):
    """Update session request"""
    name: str


class SessionChatRequest(BaseModel):
    """Chat within a session"""
    content: str
    stream: bool = True


def generate_session_name(messages: list[ChatMessage]) -> str:
    """Generate a session name from the first few messages"""
    if not messages:
        return "New Chat"
    
    # Get first user message
    user_msgs = [m for m in messages if m.role == "user"]
    if not user_msgs:
        return "New Chat"
    
    first_msg = user_msgs[0].content
    # Truncate to ~40 chars at word boundary
    if len(first_msg) <= 40:
        return first_msg
    
    truncated = first_msg[:40]
    last_space = truncated.rfind(" ")
    if last_space > 20:
        truncated = truncated[:last_space]
    return truncated + "..."


@router.get("/sessions")
async def list_sessions(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List all chat sessions with message counts"""
    from sqlalchemy import func
    from sqlalchemy.orm import selectinload
    
    # Get sessions with message count via subquery
    result = await db.execute(
        select(ChatSession)
        .order_by(ChatSession.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    sessions = result.scalars().all()
    
    # Get message counts for all sessions
    session_ids = [s.id for s in sessions]
    if session_ids:
        count_result = await db.execute(
            select(ChatMessage.session_id, func.count(ChatMessage.id))
            .where(ChatMessage.session_id.in_(session_ids))
            .group_by(ChatMessage.session_id)
        )
        counts = {row[0]: row[1] for row in count_result.fetchall()}
    else:
        counts = {}
    
    return {
        "sessions": [s.to_dict(message_count=counts.get(s.id, 0)) for s in sessions],
        "count": len(sessions),
    }


@router.post("/sessions")
async def create_session(
    data: SessionCreate = None,
    db: AsyncSession = Depends(get_db),
):
    """Create a new chat session"""
    session = ChatSession(
        name=data.name if data and data.name else None,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    
    return session.to_dict(message_count=0)


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a session with all messages"""
    from sqlalchemy.orm import selectinload
    
    result = await db.execute(
        select(ChatSession)
        .options(selectinload(ChatSession.messages))
        .where(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return session.to_dict(include_messages=True)


@router.patch("/sessions/{session_id}")
async def update_session(
    session_id: UUID,
    data: SessionUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Rename a session"""
    from sqlalchemy import func
    
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session.name = data.name
    await db.commit()
    await db.refresh(session)
    
    # Get message count
    count_result = await db.execute(
        select(func.count(ChatMessage.id)).where(ChatMessage.session_id == session_id)
    )
    msg_count = count_result.scalar() or 0
    
    return session.to_dict(message_count=msg_count)


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a session and all its messages"""
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    await db.execute(delete(ChatSession).where(ChatSession.id == session_id))
    await db.commit()
    
    return {"message": "Session deleted", "id": str(session_id)}


@router.post("/sessions/{session_id}/chat")
async def chat_in_session(
    session_id: UUID,
    request: SessionChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """Chat within a session (stores messages in DB)"""
    # Get session
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Save user message
    user_msg = ChatMessage(
        session_id=session_id,
        role="user",
        content=request.content,
    )
    user_msg.content_type = "text"
    user_msg.content_text = request.content
    user_msg.content_media = None
    db.add(user_msg)
    await db.commit()
    
    # Get all messages for context
    msgs_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    all_messages = msgs_result.scalars().all()
    messages = [{"role": _coerce_role_for_llm(m.role), "content": _coerce_content_for_llm(m)} for m in all_messages]
    
    if request.stream:
        return EventSourceResponse(
            stream_session_response(session_id, messages),
            media_type="text/event-stream"
        )
    else:
        # Non-streaming
        full_response = ""
        async for event_type, data in stream_chat(messages):
            if event_type == "text":
                full_response += data
        
        # Save assistant response
        assistant_msg = ChatMessage(
            session_id=session_id,
            role="assistant",
            content=full_response,
        )
        assistant_msg.content_type = "text"
        assistant_msg.content_text = full_response
        assistant_msg.content_media = None
        db.add(assistant_msg)
        
        # Auto-name session if not named and has 2+ messages
        if not session.name and len(all_messages) >= 1:
            all_msgs_for_name = list(all_messages) + [user_msg]
            session.name = generate_session_name(all_msgs_for_name)
        
        await db.commit()
        
        return {"role": "assistant", "content": full_response}


async def stream_session_response(session_id: UUID, messages: list[dict]):
    """Stream response and save to DB (creates own db session)"""
    from app.database import AsyncSessionLocal
    
    full_response = ""
    
    try:
        async for event_type, data in stream_chat(messages):
            if event_type == "text":
                full_response += data
                yield {
                    "event": "message",
                    "data": json.dumps({"content": data})
                }
            elif event_type == "thinking":
                yield {
                    "event": "thinking",
                    "data": json.dumps({"status": "using_tools"})
                }
        
        # Save assistant response to DB with fresh session
        async with AsyncSessionLocal() as db:
            assistant_msg = ChatMessage(
                session_id=session_id,
                role="assistant",
                content=full_response,
            )
            assistant_msg.content_type = "text"
            assistant_msg.content_text = full_response
            assistant_msg.content_media = None
            db.add(assistant_msg)
            
            # Auto-name session if needed
            result = await db.execute(
                select(ChatSession).where(ChatSession.id == session_id)
            )
            session = result.scalar_one_or_none()
            
            if session and not session.name:
                msgs_result = await db.execute(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == session_id)
                    .order_by(ChatMessage.created_at)
                )
                all_messages = msgs_result.scalars().all()
                if len(all_messages) >= 2:
                    session.name = generate_session_name(list(all_messages))
            
            await db.commit()
        
        yield {
            "event": "done",
            "data": json.dumps({"status": "complete"})
        }
        
    except Exception as e:
        error_str = str(e)
        # Parse common error types for user-friendly messages
        if "401" in error_str or "authentication_error" in error_str or "invalid x-api-key" in error_str.lower():
            user_error = "Invalid Anthropic API key. Please check your API key in Settings."
        elif "rate_limit" in error_str.lower() or "429" in error_str:
            user_error = "Rate limit exceeded. Please wait a moment and try again."
        elif "ANTHROPIC_API_KEY" in error_str:
            user_error = "Chatbot not configured. Please add your Anthropic API key in Settings."
        else:
            user_error = f"Chat error: {error_str}"
        
        yield {
            "event": "error",
            "data": json.dumps({"error": user_error})
        }
