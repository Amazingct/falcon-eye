"""Execute tool calls via the main Falcon-Eye API's generic tool execution endpoint"""
import os
import json
import httpx

API_URL = os.getenv("API_URL", "http://falcon-eye-api:8000")


async def execute_tool(name: str, arguments: dict, agent_context: dict | None = None) -> str:
    """Execute a tool by calling POST /api/tools/execute on the main API."""
    try:
        payload = {
            "tool_name": name,
            "arguments": arguments,
        }
        if agent_context:
            payload["agent_context"] = agent_context

        async with httpx.AsyncClient(base_url=API_URL, timeout=60) as client:
            res = await client.post("/api/tools/execute", json=payload)
            if res.status_code == 200:
                data = res.json()
                return data.get("result", "No result returned")
            return f"API error ({res.status_code}): {res.text[:300]}"

    except Exception as e:
        return f"Tool execution error: {e}"
