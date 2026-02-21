"""Tools registry - defines all available tools for agents"""

TOOLS_REGISTRY = {
    "camera_list": {
        "name": "list_cameras",
        "description": "Get all cameras and their current status",
        "category": "cameras",
        "parameters": {
            "type": "object",
            "properties": {},
        },
        "handler": "app.tools.handlers.list_cameras",
    },
    "camera_status": {
        "name": "camera_status",
        "description": "Check if a specific camera is online",
        "category": "cameras",
        "parameters": {
            "type": "object",
            "properties": {
                "camera_id": {"type": "string", "description": "Camera UUID"},
            },
            "required": ["camera_id"],
        },
        "handler": "app.tools.handlers.camera_status",
    },
    "camera_control": {
        "name": "control_camera",
        "description": "Start, stop, or restart a camera",
        "category": "cameras",
        "parameters": {
            "type": "object",
            "properties": {
                "camera_id": {"type": "string", "description": "Camera UUID"},
                "action": {"type": "string", "enum": ["start", "stop", "restart"], "description": "Action to perform"},
            },
            "required": ["camera_id", "action"],
        },
        "handler": "app.tools.handlers.control_camera",
    },
    "camera_snapshot": {
        "name": "camera_snapshot",
        "description": "Grab a snapshot frame from a running camera and save it to the filesystem. Returns the saved file path. Use send_media afterwards to deliver the snapshot to the user.",
        "category": "cameras",
        "parameters": {
            "type": "object",
            "properties": {
                "camera_id": {"type": "string", "description": "Camera UUID"},
            },
            "required": ["camera_id"],
        },
        "handler": "app.tools.handlers.camera_snapshot",
    },
    "recording_start": {
        "name": "start_recording",
        "description": "Start recording on a camera",
        "category": "recording",
        "parameters": {
            "type": "object",
            "properties": {
                "camera_id": {"type": "string", "description": "Camera UUID"},
            },
            "required": ["camera_id"],
        },
        "handler": "app.tools.handlers.start_recording",
    },
    "recording_stop": {
        "name": "stop_recording",
        "description": "Stop an active recording on a camera",
        "category": "recording",
        "parameters": {
            "type": "object",
            "properties": {
                "camera_id": {"type": "string", "description": "Camera UUID"},
            },
            "required": ["camera_id"],
        },
        "handler": "app.tools.handlers.stop_recording",
    },
    "recording_list": {
        "name": "list_recordings",
        "description": "Get all recordings, optionally filtered by camera",
        "category": "recording",
        "parameters": {
            "type": "object",
            "properties": {
                "camera_id": {"type": "string", "description": "Filter by camera UUID (optional)"},
            },
        },
        "handler": "app.tools.handlers.list_recordings",
    },
    "node_list": {
        "name": "list_nodes",
        "description": "Get cluster nodes and their health status",
        "category": "system",
        "parameters": {
            "type": "object",
            "properties": {},
        },
        "handler": "app.tools.handlers.list_nodes",
    },
    "node_scan": {
        "name": "scan_cameras",
        "description": "Scan cluster nodes for USB and network cameras",
        "category": "system",
        "parameters": {
            "type": "object",
            "properties": {
                "network": {"type": "boolean", "description": "Include network scan", "default": True},
            },
        },
        "handler": "app.tools.handlers.scan_cameras",
    },
    "system_info": {
        "name": "system_info",
        "description": "Get cluster resource usage and pod status",
        "category": "system",
        "parameters": {
            "type": "object",
            "properties": {},
        },
        "handler": "app.tools.handlers.system_info",
    },
    "alert_send": {
        "name": "send_alert",
        "description": "Send an alert via configured channels",
        "category": "alerts",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Alert message"},
                "severity": {"type": "string", "enum": ["info", "warning", "critical"], "default": "info"},
            },
            "required": ["message"],
        },
        "handler": "app.tools.handlers.send_alert",
    },
    "web_search": {
        "name": "web_search",
        "description": "Search the web (requires API key)",
        "category": "external",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
        "handler": "app.tools.handlers.web_search",
    },
    "agent_spawn": {
        "name": "spawn_agent",
        "description": "Create and start a new agent. Inherits calling agent's LLM config. If 'task' is provided, the agent runs as a one-off K8s Job (not a Deployment) — this tool returns immediately so you can continue working. The result will be delivered to your session once the Job finishes, and the ephemeral agent is automatically cleaned up. Do NOT call this repeatedly for the same task.",
        "category": "agents",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Agent display name"},
                "system_prompt": {"type": "string", "description": "System prompt (optional — defaults to generic)"},
                "tools": {"type": "array", "items": {"type": "string"}, "description": "Tool IDs to enable (optional — inherits parent's tools)"},
                "channel_type": {"type": "string", "enum": ["telegram", "webhook", "custom"], "description": "Channel type (optional — inherits parent's)"},
                "task": {"type": "string", "description": "A task for the agent to execute as a background Job. The result is delivered asynchronously once complete."},
            },
            "required": ["name"],
        },
        "handler": "app.tools.handlers.spawn_agent",
    },
    "agent_delegate": {
        "name": "delegate_task",
        "description": "Send a task to an already-running agent asynchronously. Returns immediately so you can continue working. The result will be delivered to your session as a system message once the target agent finishes.",
        "category": "agents",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "UUID of the target agent (must be running)"},
                "task": {"type": "string", "description": "The task or question to send to the agent"},
            },
            "required": ["agent_id", "task"],
        },
        "handler": "app.tools.handlers.delegate_task",
    },
    "agent_create_from": {
        "name": "clone_agent",
        "description": "Create a new agent by cloning an existing agent's configuration",
        "category": "agents",
        "parameters": {
            "type": "object",
            "properties": {
                "source_agent_id": {"type": "string", "description": "UUID of the agent to clone"},
                "new_name": {"type": "string", "description": "Name for the new agent"},
                "override_system_prompt": {"type": "string", "description": "Override the cloned system prompt (optional)"},
                "override_tools": {"type": "array", "items": {"type": "string"}, "description": "Override the cloned tool list (optional)"},
            },
            "required": ["source_agent_id", "new_name"],
        },
        "handler": "app.tools.handlers.clone_agent",
    },
    "cron_create": {
        "name": "create_cron_job",
        "description": "Create a scheduled cron job that sends a prompt to you on a recurring schedule. Results are delivered to your current chat session. Use standard cron expressions (e.g., '0 9 * * *' for every day at 9 AM, '*/30 * * * *' for every 30 minutes).",
        "category": "scheduling",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Display name for the cron job (e.g., 'Morning camera check')"},
                "cron_expr": {"type": "string", "description": "Cron expression (e.g., '0 9 * * *' for daily at 9 AM UTC)"},
                "prompt": {"type": "string", "description": "The prompt/instruction to execute on each run"},
                "timezone": {"type": "string", "description": "Timezone (default: UTC)", "default": "UTC"},
                "timeout_seconds": {"type": "integer", "description": "Max execution time in seconds (default: 120)", "default": 120},
            },
            "required": ["name", "cron_expr", "prompt"],
        },
        "handler": "app.tools.handlers.create_cron_job",
    },
    "cron_list": {
        "name": "list_cron_jobs",
        "description": "List all your scheduled cron jobs with their schedule, status, and last run result.",
        "category": "scheduling",
        "parameters": {
            "type": "object",
            "properties": {},
        },
        "handler": "app.tools.handlers.list_cron_jobs",
    },
    "cron_delete": {
        "name": "delete_cron_job",
        "description": "Delete a scheduled cron job by ID.",
        "category": "scheduling",
        "parameters": {
            "type": "object",
            "properties": {
                "cron_id": {"type": "string", "description": "UUID of the cron job to delete"},
            },
            "required": ["cron_id"],
        },
        "handler": "app.tools.handlers.delete_cron_job",
    },
    "camera_analyze": {
        "name": "analyze_camera",
        "description": "Capture frames from a camera and analyze what's happening using vision AI. In 'clip' mode, captures 1 frame per second over the duration (e.g. 5 frames over 5 seconds). Returns an AI-generated description of what the camera sees. Always use 'clip' mode when the user asks to analyze or describe what a camera is seeing.",
        "category": "cameras",
        "parameters": {
            "type": "object",
            "properties": {
                "camera_id": {"type": "string", "description": "Camera UUID"},
                "mode": {"type": "string", "enum": ["snapshot", "clip"], "description": "Single frame (snapshot) or multi-frame analysis (clip). Use 'clip' for analyzing activity.", "default": "clip"},
                "duration": {"type": "integer", "minimum": 3, "maximum": 10, "description": "Number of seconds to capture (clip mode). Each second = 1 frame.", "default": 5},
            },
            "required": ["camera_id"],
        },
        "handler": "app.tools.handlers.analyze_camera",
    },
    "custom_api": {
        "name": "custom_api_call",
        "description": "Call a user-defined HTTP endpoint",
        "category": "external",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to call"},
                "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"], "default": "GET"},
                "body": {"type": "string", "description": "Request body (JSON string)"},
            },
            "required": ["url"],
        },
        "handler": "app.tools.handlers.custom_api_call",
    },
    "file_write": {
        "name": "write_file",
        "description": "Write text content to a file in the shared agent filesystem. Creates parent directories automatically. Use paths like 'notes/report.txt' or 'data/output.json'.",
        "category": "filesystem",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to the shared root (e.g. 'notes/report.txt')"},
                "content": {"type": "string", "description": "Text content to write"},
            },
            "required": ["path", "content"],
        },
        "handler": "app.tools.handlers.file_write",
    },
    "file_read": {
        "name": "read_file",
        "description": "Read the contents of a text file from the shared agent filesystem.",
        "category": "filesystem",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to the shared root (e.g. 'notes/report.txt')"},
            },
            "required": ["path"],
        },
        "handler": "app.tools.handlers.file_read",
    },
    "file_list": {
        "name": "list_files",
        "description": "List files and directories in the shared agent filesystem. Use a prefix to browse subdirectories.",
        "category": "filesystem",
        "parameters": {
            "type": "object",
            "properties": {
                "prefix": {"type": "string", "description": "Directory path to list (empty for root)", "default": ""},
            },
        },
        "handler": "app.tools.handlers.file_list",
    },
    "send_media": {
        "name": "send_media",
        "description": "Send an image, video, or document from the shared filesystem to the user's chat. The file must already exist (use write_file or list_files first). For camera snapshots, use camera_snapshot then send the resulting file.",
        "category": "messaging",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path in the shared filesystem (e.g. 'photos/snapshot.jpg')"},
                "caption": {"type": "string", "description": "Caption to display with the media (optional)", "default": ""},
                "media_type": {"type": "string", "enum": ["auto", "photo", "video", "document"], "description": "Force a specific media type, or 'auto' to detect from file extension", "default": "auto"},
            },
            "required": ["path"],
        },
        "handler": "app.tools.handlers.send_media",
    },
    "file_delete": {
        "name": "delete_file",
        "description": "Delete a file from the shared agent filesystem.",
        "category": "filesystem",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to delete"},
            },
            "required": ["path"],
        },
        "handler": "app.tools.handlers.file_delete",
    },
}


def get_openai_function_schema(tool_id: str) -> dict:
    """Convert a tool registry entry to OpenAI function calling schema"""
    tool = TOOLS_REGISTRY[tool_id]
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"],
        },
    }


def get_tools_for_agent(tool_ids: list[str]) -> list[dict]:
    """Get OpenAI function schemas for a list of tool IDs"""
    return [get_openai_function_schema(tid) for tid in tool_ids if tid in TOOLS_REGISTRY]


def get_tools_grouped() -> dict:
    """Get all tools grouped by category"""
    grouped = {}
    for tool_id, tool in TOOLS_REGISTRY.items():
        cat = tool["category"]
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append({
            "id": tool_id,
            "name": tool["name"],
            "description": tool["description"],
            "category": cat,
            "parameters": tool["parameters"],
        })
    return grouped
