"""Execute tool calls via HTTP to the main Falcon-Eye API"""
import os
import json
import httpx

API_URL = os.getenv("API_URL", "http://falcon-eye-api:8000")
AGENT_ID = os.getenv("AGENT_ID", "")

# Map tool names to API endpoints and methods
TOOL_API_MAP = {
    "list_cameras": {"method": "GET", "path": "/api/cameras/"},
    "camera_status": {"method": "GET", "path": "/api/cameras/{camera_id}"},
    "control_camera": {"method": "POST", "path": "/api/cameras/{camera_id}/{action}"},
    "start_recording": {"method": "POST", "path": "/api/cameras/{camera_id}/recording/start"},
    "stop_recording": {"method": "POST", "path": "/api/cameras/{camera_id}/recording/stop"},
    "list_recordings": {"method": "GET", "path": "/api/recordings/"},
    "list_nodes": {"method": "GET", "path": "/api/nodes/"},
    "scan_cameras": {"method": "GET", "path": "/api/nodes/scan/cameras"},
    "system_info": {"method": "GET", "path": "/api/nodes/"},
}


async def execute_tool(name: str, arguments: dict) -> str:
    """Execute a tool call by proxying to the main API.

    For tools we have a direct mapping, call the API endpoint.
    For everything else, fall back to a generic tool execution endpoint.
    """
    try:
        mapping = TOOL_API_MAP.get(name)
        if mapping:
            path = mapping["path"].format(**arguments)
            method = mapping["method"]
            async with httpx.AsyncClient(base_url=API_URL, timeout=30) as client:
                if method == "GET":
                    res = await client.get(path)
                else:
                    res = await client.post(path)
                return json.dumps(res.json()) if res.status_code < 400 else f"API error ({res.status_code}): {res.text[:300]}"

        # Fallback: send to chat endpoint which handles tools internally
        return f"Tool '{name}' not directly mapped. Args: {json.dumps(arguments)}"

    except Exception as e:
        return f"Tool execution error: {e}"
