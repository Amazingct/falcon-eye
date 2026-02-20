# Gateway & Agent System - Design Document

## Overview

Add a multi-agent system to Falcon-Eye that allows:
1. **Multiple chat agents** — each runs as a separate pod with its own LLM context
2. **External channel connections** — Telegram bot, webhooks, etc.
3. **Scheduled prompts (Cron)** — run prompts on specific agents at set times
4. **Agent management UI** — create, configure, and monitor agents from the dashboard

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Dashboard (React)                     │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ Chat Tab │  │ Agents Page  │  │ Cron Jobs Page    │  │
│  │(per agent)│  │(CRUD agents) │  │(schedule prompts) │  │
│  └──────────┘  └──────────────┘  └───────────────────┘  │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP
┌────────────────────────▼────────────────────────────────┐
│                   Main API (FastAPI)                     │
│  ┌────────────┐ ┌────────────┐ ┌─────────────────────┐  │
│  │ /api/agents│ │/api/cron   │ │/api/chat/{agent_id} │  │
│  │  CRUD      │ │ CRUD+exec  │ │  send/history       │  │
│  └────────────┘ └────────────┘ └─────────────────────┘  │
│  ┌─────────────────────────────────────────────────────┐ │
│  │           Agent Manager (K8s Controller)            │ │
│  │  - Spawns/kills agent pods                          │ │
│  │  - Manages Telegram bot connections                 │ │
│  │  - Routes messages to correct agent pod             │ │
│  └─────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────┐ │
│  │           Cron Scheduler (APScheduler)              │ │
│  │  - Reads cron jobs from DB                          │ │
│  │  - Sends prompts to target agent at scheduled time  │ │
│  └─────────────────────────────────────────────────────┘ │
└──────────────────┬──────────────────────────────────────┘
                   │
        ┌──────────┼──────────┐
        ▼          ▼          ▼
   ┌─────────┐ ┌─────────┐ ┌─────────┐
   │ Agent   │ │ Agent   │ │ Agent   │
   │ "main"  │ │ "tg-bot"│ │ "patrol"│
   │ (built  │ │ (pod)   │ │ (pod)   │
   │  into   │ │         │ │         │
   │  API)   │ │ Telegram│ │ Cron-   │
   │         │ │ Bot     │ │ driven  │
   └────┬────┘ └────┬────┘ └────┬────┘
        │           │           │
        └─────┬─────┘───────────┘
              ▼
   ┌──────────────────┐
   │   PostgreSQL     │
   │  ┌────────────┐  │
   │  │ agents     │  │
   │  │ chat_hist  │  │
   │  │ cron_jobs  │  │
   │  └────────────┘  │
   └──────────────────┘
```

---

## Database Schema

### `agents` table
```sql
CREATE TABLE agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,           -- "Main Assistant", "Telegram Bot", "Night Patrol"
    slug VARCHAR(50) UNIQUE NOT NULL,     -- "main", "tg-bot", "patrol" (used in URLs)
    type VARCHAR(20) NOT NULL,            -- "built-in" | "pod"
    status VARCHAR(20) DEFAULT 'stopped', -- "running" | "stopped" | "error" | "creating"
    
    -- LLM Configuration
    provider VARCHAR(50) NOT NULL,        -- "openai" | "anthropic" | "ollama"
    model VARCHAR(100) NOT NULL,          -- "gpt-4o" | "claude-3-5-sonnet" | "tinyllama"
    api_key_ref VARCHAR(100),             -- K8s secret key name (null = use default)
    system_prompt TEXT,                   -- Custom system prompt
    temperature FLOAT DEFAULT 0.7,
    max_tokens INT DEFAULT 4096,
    
    -- Channel Configuration (for gateway agents)
    channel_type VARCHAR(20),             -- null | "telegram" | "webhook" | "discord"
    channel_config JSONB DEFAULT '{}',    -- {"bot_token": "...", "allowed_chat_ids": [...]}
    
    -- K8s Configuration (for pod agents)
    deployment_name VARCHAR(255),
    service_name VARCHAR(255),
    node_name VARCHAR(255),               -- Preferred node
    
    -- Tools (subset of available tools)
    tools JSONB DEFAULT '[]',             -- ["camera_status", "camera_control", "recording", "system_info"]
    
    -- Resource limits
    cpu_limit VARCHAR(20) DEFAULT '500m',
    memory_limit VARCHAR(20) DEFAULT '512Mi',
    
    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### `chat_messages` table (replaces/extends existing chat)
```sql
CREATE TABLE chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    session_id VARCHAR(100) NOT NULL,      -- Groups messages into conversations
    role VARCHAR(20) NOT NULL,             -- "user" | "assistant" | "system"
    content TEXT NOT NULL,
    
    -- Source tracking
    source VARCHAR(50),                    -- "dashboard" | "telegram" | "cron" | "api"
    source_user VARCHAR(100),              -- Telegram username, dashboard user, etc.
    
    -- Token usage
    prompt_tokens INT,
    completion_tokens INT,
    
    created_at TIMESTAMP DEFAULT NOW(),
    
    -- Index for fast history lookups
    INDEX idx_agent_session (agent_id, session_id, created_at)
);
```

### `cron_jobs` table
```sql
CREATE TABLE cron_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,            -- "Morning Camera Check"
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    
    -- Schedule
    cron_expr VARCHAR(100) NOT NULL,       -- "0 8 * * *" (standard cron)
    timezone VARCHAR(50) DEFAULT 'UTC',
    
    -- Prompt
    prompt TEXT NOT NULL,                  -- "Check all cameras and report any offline ones"
    
    -- K8s CronJob
    cronjob_name VARCHAR(255),            -- K8s CronJob resource name
    enabled BOOLEAN DEFAULT TRUE,
    
    -- Execution tracking
    last_run TIMESTAMP,
    last_result TEXT,                      -- Summary of last execution
    last_status VARCHAR(20),              -- "success" | "failed" | "timeout"
    
    -- Limits
    timeout_seconds INT DEFAULT 120,
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### Cron Job as K8s CronJob

Each cron job creates a **real K8s CronJob** resource. When triggered, it spins up a short-lived pod that:
1. Sends the prompt to the target agent via `POST /api/chat/{agent_id}/send`
2. Waits for response
3. Stores result back via `PATCH /api/cron/{id}` (last_run, last_result, last_status)
4. Exits (pod cleaned up by K8s)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: cron-morning-check
  namespace: falcon-eye
  labels:
    app: falcon-eye
    component: cron
    cron-id: <uuid>
spec:
  schedule: "0 8 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: cron-runner
            image: ghcr.io/amazingct/falcon-eye-cron-runner:latest
            env:
            - name: API_URL
              value: "http://falcon-eye-api.falcon-eye.svc.cluster.local:8000"
            - name: AGENT_ID
              value: "<target-agent-uuid>"
            - name: CRON_JOB_ID
              value: "<cron-job-uuid>"
            - name: PROMPT
              value: "Check all cameras and report any offline ones"
            - name: TIMEOUT_SECONDS
              value: "120"
            resources:
              requests: { memory: "64Mi", cpu: "50m" }
              limits: { memory: "128Mi", cpu: "200m" }
          restartPolicy: Never
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
```

**Cron Runner Image** — Ultra-lightweight (~20MB):
```dockerfile
FROM python:3.11-slim
RUN pip install httpx
COPY cron_runner.py /app/
CMD ["python", "/app/cron_runner.py"]
```

```python
# cron_runner.py - sends prompt to agent and reports result
import os, httpx, sys

API_URL = os.getenv("API_URL")
AGENT_ID = os.getenv("AGENT_ID") 
CRON_JOB_ID = os.getenv("CRON_JOB_ID")
PROMPT = os.getenv("PROMPT")
TIMEOUT = int(os.getenv("TIMEOUT_SECONDS", "120"))

with httpx.Client(timeout=TIMEOUT) as client:
    # Send prompt to agent
    r = client.post(f"{API_URL}/api/chat/{AGENT_ID}/send", 
                    json={"message": PROMPT, "source": "cron"})
    result = r.json()
    
    # Report result back
    client.patch(f"{API_URL}/api/cron/{CRON_JOB_ID}", json={
        "last_run": result["timestamp"],
        "last_result": result["response"][:1000],
        "last_status": "success" if r.status_code == 200 else "failed"
    })
```

---

## Agent Types

### 1. Built-in Agent ("main")
- Runs inside the main API process (no separate pod)
- Default agent for dashboard chat
- Always exists, cannot be deleted
- Created automatically on first install

### 2. Pod Agent (Telegram Bot, Custom)
- Runs as a separate K8s Deployment
- Lightweight container with:
  - LLM client (OpenAI/Anthropic/Ollama SDK)
  - Channel connector (Telegram bot polling, webhook server)
  - Chat history via API calls back to main API
- Each pod has its own system prompt and model config
- Can be stopped/started independently

### 3. Cron Agent
- A pod agent that also processes scheduled prompts
- Or any agent can be targeted by cron jobs

---

## Agent Pod Image

Single `falcon-eye-agent` Docker image that handles all agent types:

```dockerfile
FROM python:3.11-slim
RUN pip install openai anthropic python-telegram-bot httpx apscheduler
COPY agent/ /app/
CMD ["python", "/app/main.py"]
```

Environment variables configure behavior:
- `AGENT_ID` — UUID
- `AGENT_SLUG` — slug name
- `API_URL` — Main Falcon-Eye API URL
- `CHANNEL_TYPE` — "telegram" | "webhook" | "" 
- `TELEGRAM_BOT_TOKEN` — For Telegram agents
- `LLM_PROVIDER` — "openai" | "anthropic" | "ollama"
- `LLM_MODEL` — Model name
- `LLM_API_KEY` — API key (or from K8s secret)
- `LLM_BASE_URL` — For Ollama or custom endpoints
- `SYSTEM_PROMPT` — System prompt text

---

## API Endpoints

### Agents
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/agents/` | List all agents |
| POST | `/api/agents/` | Create agent |
| GET | `/api/agents/{id}` | Get agent details |
| PATCH | `/api/agents/{id}` | Update agent config |
| DELETE | `/api/agents/{id}` | Delete agent + pod |
| POST | `/api/agents/{id}/start` | Start agent pod |
| POST | `/api/agents/{id}/stop` | Stop agent pod |

### Chat (per agent)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/chat/{agent_id}/history` | Get chat history |
| POST | `/api/chat/{agent_id}/send` | Send message to agent |
| GET | `/api/chat/{agent_id}/sessions` | List chat sessions |
| POST | `/api/chat/{agent_id}/sessions/new` | Start new session |

### Cron Jobs
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/cron/` | List all cron jobs |
| POST | `/api/cron/` | Create cron job |
| PATCH | `/api/cron/{id}` | Update cron job |
| DELETE | `/api/cron/{id}` | Delete cron job |
| POST | `/api/cron/{id}/run` | Run now (manual trigger) |
| GET | `/api/cron/{id}/history` | Get execution history |

---

## Dashboard UI Pages

### 1. Agents Page (`/agents`)
- List all agents with status badges (running/stopped/error)
- Create new agent modal:
  - Name, type (Telegram/Webhook/Custom)
  - LLM provider + model selection
  - System prompt editor
  - Channel config (Telegram bot token, etc.)
  - Resource limits
- Agent detail/edit panel
- Start/Stop/Delete buttons
- Live status indicator

### 2. Agent Chat (`/chat/{agent_slug}`)
- Chat interface per agent (existing chat UI, extended)
- Session selector dropdown
- "New Session" button
- Shows source badge on messages (dashboard/telegram/cron)

### 3. Cron Jobs Page (`/cron`)
- List all cron jobs with next run time
- Create/edit modal:
  - Name
  - Target agent (dropdown)
  - Cron expression + human-readable preview
  - Prompt textarea
  - Timezone selector
  - Enable/disable toggle
- "Run Now" button
- Execution history per job

### 4. Settings → Gateway Tab
- Default LLM provider/model/API key
- Agent pod image override
- Max concurrent agents

---

## Implementation Plan

### Phase 1: Database + API (Backend)
1. Add `agents`, `chat_messages`, `cron_jobs` tables
2. Migrate existing chat history to new schema
3. Implement agent CRUD API
4. Implement per-agent chat API
5. Create "main" agent on startup

### Phase 2: Agent Pod System
6. Build `falcon-eye-agent` Docker image
7. Implement agent pod lifecycle in K8s service
8. Telegram bot connector
9. Message routing (API → agent pod ↔ LLM)

### Phase 3: Cron System
10. K8s CronJob resource generation (like camera deployments)
11. Cron job CRUD API (creates/updates/deletes K8s CronJobs)
12. Cron runner image — lightweight pod that sends prompt to target agent via API

### Phase 4: Dashboard UI
13. Agents management page
14. Per-agent chat with session management
15. Cron jobs management page
16. Settings → Gateway configuration

---

## Tools System

Each agent gets access to a configurable subset of available tools. Tools are function-calling capabilities the LLM can invoke.

### Available Tools Registry

| Tool ID | Name | Description | Category |
|---------|------|-------------|----------|
| `camera_list` | List Cameras | Get all cameras and their status | Cameras |
| `camera_status` | Camera Status | Check if a specific camera is online | Cameras |
| `camera_control` | Camera Control | Start/stop/restart cameras | Cameras |
| `camera_snapshot` | Camera Snapshot | Grab a frame from a camera | Cameras |
| `recording_start` | Start Recording | Start recording on a camera | Recording |
| `recording_stop` | Stop Recording | Stop an active recording | Recording |
| `recording_list` | List Recordings | Get all recordings | Recording |
| `node_list` | List Nodes | Get cluster nodes and health | System |
| `node_scan` | Scan Cameras | Scan nodes for USB/network cameras | System |
| `system_info` | System Info | Get cluster resource usage, pod status | System |
| `alert_send` | Send Alert | Send alert via configured channels | Alerts |
| `web_search` | Web Search | Search the web (requires API key) | External |
| `custom_api` | Custom API Call | Call a user-defined HTTP endpoint | External |

### Per-Agent Tool Configuration

In the Agents page, each agent shows a **Tools** section with checkboxes:

```
┌─ Tools ──────────────────────────────────────┐
│                                              │
│  📷 Cameras                                  │
│  ☑ List Cameras                              │
│  ☑ Camera Status                             │
│  ☐ Camera Control (start/stop/restart)       │
│  ☐ Camera Snapshot                           │
│                                              │
│  🎬 Recording                                │
│  ☐ Start Recording                           │
│  ☐ Stop Recording                            │
│  ☑ List Recordings                           │
│                                              │
│  🖥 System                                    │
│  ☑ List Nodes                                │
│  ☐ Scan Cameras                              │
│  ☑ System Info                               │
│                                              │
│  🔔 Alerts                                   │
│  ☐ Send Alert                                │
│                                              │
│  🌐 External                                 │
│  ☐ Web Search                                │
│  ☐ Custom API Call                           │
│                                              │
└──────────────────────────────────────────────┘
```

### Tool Implementation

Tools are defined in a central registry (`app/tools/registry.py`):

```python
TOOLS_REGISTRY = {
    "camera_list": {
        "name": "list_cameras",
        "description": "Get all cameras and their current status",
        "category": "cameras",
        "parameters": {},  # OpenAI function schema
        "handler": "app.tools.cameras.list_cameras",
    },
    "camera_control": {
        "name": "control_camera",
        "description": "Start, stop, or restart a camera",
        "category": "cameras",
        "parameters": {
            "type": "object",
            "properties": {
                "camera_id": {"type": "string"},
                "action": {"type": "string", "enum": ["start", "stop", "restart"]}
            },
            "required": ["camera_id", "action"]
        },
        "handler": "app.tools.cameras.control_camera",
    },
    # ... etc
}
```

When sending a message to an agent, only the tools in that agent's `tools` list are included in the LLM function-calling schema. This means:
- A **read-only monitoring bot** gets: `camera_list`, `camera_status`, `recording_list`, `system_info`
- A **full control bot** gets all tools
- A **Telegram alert bot** gets: `camera_status`, `alert_send`

### API Endpoints for Tools

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tools/` | List all available tools with categories |
| GET | `/api/agents/{id}/tools` | Get tools assigned to agent |
| PUT | `/api/agents/{id}/tools` | Set tools for agent (list of tool IDs) |

---

## Key Design Decisions

1. **Agents as pods** — Isolation, independent scaling, separate crash domains
2. **Chat via main API** — All chat history stored centrally, agents call back to API
3. **Cron in main API** — Single scheduler, avoids duplicate execution
4. **Agent image is generic** — One image, configured via env vars
5. **Sessions** — Each agent can have multiple sessions (conversations)
6. **Main agent is built-in** — No pod overhead for the default chat
7. **Cron as K8s CronJobs** — Native scheduling, survives API restarts, visible via kubectl, tiny runner pods that exit after execution
8. **Chat continuity** — Sub-agents (pod agents) always continue from their latest chat history (persistent context). The main/built-in agent does NOT persist history — it powers the dashboard chatbot which starts fresh each page load. This means:
   - **Pod agents** (Telegram bot, patrol bot, etc.): Load full chat history on every message → maintains long-running context, remembers previous conversations
   - **Main agent**: Stateless per session → dashboard chat starts clean, user can still view history but LLM doesn't carry it forward
   - Rationale: Pod agents are autonomous and need memory to function (e.g. "check on what you found yesterday"). The dashboard chat is interactive and user-driven — fresh context avoids token bloat and keeps responses fast
