"""Agent API routes"""
from uuid import UUID
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field

from app.database import get_db
from app.models.agent import Agent
from app.services import k8s
from app.tools.registry import TOOLS_REGISTRY

router = APIRouter(prefix="/api/agents", tags=["agents"])


class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=50)
    type: str = Field(default="pod")  # built-in | pod
    provider: str = Field(default="openai")
    model: str = Field(default="gpt-4o")
    api_key_ref: Optional[str] = None
    system_prompt: Optional[str] = None
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=4096, ge=1)
    channel_type: Optional[str] = None
    channel_config: dict = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list)
    node_name: Optional[str] = None
    cpu_limit: str = "500m"
    memory_limit: str = "512Mi"


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key_ref: Optional[str] = None
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    channel_type: Optional[str] = None
    channel_config: Optional[dict] = None
    tools: Optional[list[str]] = None
    node_name: Optional[str] = None
    cpu_limit: Optional[str] = None
    memory_limit: Optional[str] = None


@router.get("/")
async def list_agents(db: AsyncSession = Depends(get_db)):
    """List all agents"""
    result = await db.execute(select(Agent).order_by(Agent.created_at.asc()))
    agents = result.scalars().all()
    return {"agents": [a.to_dict() for a in agents]}


@router.post("/", status_code=201)
async def create_agent(data: AgentCreate, db: AsyncSession = Depends(get_db)):
    """Create a new agent"""
    # Check slug uniqueness
    existing = await db.execute(select(Agent).where(Agent.slug == data.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Agent with slug '{data.slug}' already exists")

    agent = Agent(
        name=data.name,
        slug=data.slug,
        type=data.type,
        provider=data.provider,
        model=data.model,
        api_key_ref=data.api_key_ref,
        system_prompt=data.system_prompt,
        temperature=data.temperature,
        max_tokens=data.max_tokens,
        channel_type=data.channel_type,
        channel_config=data.channel_config,
        tools=data.tools,
        node_name=data.node_name,
        cpu_limit=data.cpu_limit,
        memory_limit=data.memory_limit,
        status="stopped",
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent.to_dict()


@router.get("/{agent_id}")
async def get_agent(agent_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get agent details"""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent.to_dict()


@router.patch("/{agent_id}")
async def update_agent(agent_id: UUID, data: AgentUpdate, db: AsyncSession = Depends(get_db)):
    """Update agent configuration"""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(agent, field, value)

    await db.commit()
    await db.refresh(agent)
    return agent.to_dict()


@router.delete("/{agent_id}")
async def delete_agent(agent_id: UUID, db: AsyncSession = Depends(get_db)):
    """Delete agent and its K8s resources"""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if agent.slug == "main":
        raise HTTPException(status_code=400, detail="Cannot delete the main agent")

    # Delete K8s resources if running
    if agent.deployment_name:
        try:
            await k8s.delete_agent_deployment(agent.deployment_name, agent.service_name)
        except Exception:
            pass

    await db.delete(agent)
    await db.commit()
    return {"message": "Agent deleted", "id": str(agent_id)}


@router.post("/{agent_id}/start")
async def start_agent(agent_id: UUID, db: AsyncSession = Depends(get_db)):
    """Start an agent pod"""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if agent.status == "running":
        return {"message": "Agent already running", "id": str(agent_id)}

    try:
        agent.status = "creating"
        await db.commit()

        k8s_result = await k8s.create_agent_deployment(agent)
        agent.deployment_name = k8s_result["deployment_name"]
        agent.service_name = k8s_result["service_name"]
        agent.status = "running"
        await db.commit()

        return {"message": "Agent started", "id": str(agent_id)}
    except Exception as e:
        agent.status = "error"
        await db.commit()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{agent_id}/stop")
async def stop_agent(agent_id: UUID, db: AsyncSession = Depends(get_db)):
    """Stop an agent pod"""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if agent.slug == "main":
        raise HTTPException(status_code=400, detail="Cannot stop the main agent")

    if agent.deployment_name:
        try:
            await k8s.delete_agent_deployment(agent.deployment_name, agent.service_name)
        except Exception:
            pass

    agent.status = "stopped"
    agent.deployment_name = None
    agent.service_name = None
    await db.commit()
    return {"message": "Agent stopped", "id": str(agent_id)}


async def ensure_main_agent(db: AsyncSession):
    """Auto-create the main agent as a pod and ensure it's deployed"""
    MAIN_TOOLS = list(TOOLS_REGISTRY.keys())
    MAIN_PROMPT = (
        "You are Falcon-Eye's AI assistant — a helpful, friendly operator for a distributed camera surveillance system running on Kubernetes.\n\n"
        "You can:\n"
        "- List, check status, start/stop/restart cameras\n"
        "- Take snapshots and analyze camera feeds with vision AI\n"
        "- Start/stop recordings and list existing recordings\n"
        "- Check cluster nodes, system health, and resource usage\n"
        "- Scan for USB and network cameras on cluster nodes\n"
        "- Send alerts via configured channels\n"
        "- Create, read, list, and delete files on the shared agent filesystem\n"
        "- Spawn new agents or clone existing agent configurations\n\n"
        "When a user asks you to create or write a file, use the file_write tool. "
        "When they ask to read a file, use file_read. For listing files use file_list.\n\n"
        "Be concise and helpful. Use markdown formatting when it improves readability."
    )

    result = await db.execute(select(Agent).where(Agent.slug == "main"))
    agent = result.scalar_one_or_none()

    if agent:
        # Update tools/prompt if changed
        changed = False
        if set(agent.tools or []) != set(MAIN_TOOLS):
            agent.tools = MAIN_TOOLS
            changed = True
        if agent.system_prompt != MAIN_PROMPT:
            agent.system_prompt = MAIN_PROMPT
            changed = True
        # Migrate built-in -> pod
        if agent.type == "built-in":
            agent.type = "pod"
            changed = True
        if changed:
            await db.commit()
            await db.refresh(agent)
    else:
        agent = Agent(
            name="Main Assistant",
            slug="main",
            type="pod",
            status="stopped",
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            system_prompt=MAIN_PROMPT,
            tools=MAIN_TOOLS,
        )
        db.add(agent)
        await db.commit()
        await db.refresh(agent)

    # Auto-deploy if not running
    if agent.status != "running":
        try:
            k8s_result = await k8s.create_agent_deployment(agent)
            agent.deployment_name = k8s_result["deployment_name"]
            agent.service_name = k8s_result["service_name"]
            agent.status = "running"
            await db.commit()
        except Exception as e:
            print(f"Warning: Failed to auto-deploy main agent: {e}")
            agent.status = "error"
            await db.commit()
