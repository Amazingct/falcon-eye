"""Tools API routes"""
from uuid import UUID
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.database import get_db
from app.models.agent import Agent
from app.tools.registry import TOOLS_REGISTRY, get_tools_grouped

router = APIRouter(tags=["tools"])


class ToolsUpdate(BaseModel):
    tools: list[str]


@router.get("/api/tools/")
async def list_tools():
    """List all available tools grouped by category"""
    grouped = get_tools_grouped()
    return {"tools": grouped}


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


@router.put("/api/agents/{agent_id}/tools")
async def set_agent_tools(agent_id: UUID, data: ToolsUpdate, db: AsyncSession = Depends(get_db)):
    """Set tools for an agent"""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Validate tool IDs
    invalid = [t for t in data.tools if t not in TOOLS_REGISTRY]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Unknown tool IDs: {invalid}")

    agent.tools = data.tools
    await db.commit()
    await db.refresh(agent)

    return {"agent_id": str(agent_id), "tools": agent.tools}
