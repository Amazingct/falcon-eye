"""Tools API routes"""
from uuid import UUID
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.database import get_db
from app.models.agent import Agent
from app.tools.registry import TOOLS_REGISTRY, get_tools_grouped, get_tools_for_agent
from app.tools.handlers import execute_tool

router = APIRouter(tags=["tools"])


class ToolsUpdate(BaseModel):
    tools: list[str]


class ToolExecuteRequest(BaseModel):
    tool_name: str
    arguments: dict = {}
    agent_context: Optional[dict] = None


@router.get("/api/tools/")
async def list_tools():
    """List all available tools grouped by category"""
    grouped = get_tools_grouped()
    return {"tools": grouped}


@router.post("/api/tools/execute")
async def execute_tool_endpoint(data: ToolExecuteRequest):
    """Execute a tool by name. Used by agent pods to run tools via the API."""
    try:
        result, media = await execute_tool(data.tool_name, data.arguments, agent_context=data.agent_context)
        resp: dict = {"result": result}
        if media:
            resp["media"] = media
        return resp
    except Exception as e:
        return {"result": f"Tool execution error: {e}", "error": True}


@router.get("/api/agents/{agent_id}/tools")
async def get_agent_tools(agent_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get tools assigned to an agent"""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent_tool_ids = agent.tools or []
    tools = []
    for tid in agent_tool_ids:
        if tid in TOOLS_REGISTRY:
            tool = TOOLS_REGISTRY[tid]
            tools.append({
                "id": tid,
                "name": tool["name"],
                "description": tool["description"],
                "category": tool["category"],
            })

    return {"agent_id": str(agent_id), "tools": tools}


@router.get("/api/agents/{agent_id}/chat-config")
async def get_agent_chat_config(agent_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get everything the agent pod needs for chat: tool schemas, system prompt, config.
    Used by agent pods handling Telegram/webhook messages autonomously."""
    import os
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent_tool_ids = agent.tools or []
    tools_schema = get_tools_for_agent(agent_tool_ids) if agent_tool_ids else []

    resolved_key = agent.api_key_ref or ""
    if not resolved_key:
        if agent.provider == "anthropic":
            resolved_key = os.getenv("ANTHROPIC_API_KEY", "")
        elif agent.provider == "openai":
            resolved_key = os.getenv("OPENAI_API_KEY", "")

    return {
        "agent_id": str(agent_id),
        "system_prompt": agent.system_prompt or "You are a helpful AI assistant.",
        "provider": agent.provider,
        "model": agent.model,
        "api_key": resolved_key,
        "max_tokens": agent.max_tokens,
        "temperature": agent.temperature,
        "tools_schema": tools_schema,
    }


@router.put("/api/agents/{agent_id}/tools")
async def set_agent_tools(agent_id: UUID, data: ToolsUpdate, db: AsyncSession = Depends(get_db)):
    """Set tools for an agent"""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    invalid = [t for t in data.tools if t not in TOOLS_REGISTRY]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Unknown tool IDs: {invalid}")

    agent.tools = data.tools
    await db.commit()
    await db.refresh(agent)

    return {"agent_id": str(agent_id), "tools": agent.tools}
