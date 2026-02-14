"""
Chatbot API routes with SSE streaming
"""
import json
import asyncio
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.chatbot.graph import stream_chat, create_graph

router = APIRouter(prefix="/api/chat", tags=["chatbot"])


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
        async for chunk in stream_chat(messages):
            full_response += chunk
        
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
            "data": json.dumps({"error": str(e)})
        }
    except Exception as e:
        yield {
            "event": "error", 
            "data": json.dumps({"error": f"Chat error: {str(e)}"})
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
