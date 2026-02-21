"""Build LangChain tools dynamically from OpenAI function schemas.

Each tool proxies execution to the main API's /api/tools/execute endpoint,
so all tool logic stays in the API pod while the agent pod only handles LLM orchestration.

Media items (from send_media) are collected in a shared list that the caller
can read after the agent run completes.
"""
import os
from typing import Optional

import httpx
from pydantic import BaseModel, Field, create_model
from langchain_core.tools import StructuredTool

API_URL = os.getenv("API_URL", "http://falcon-eye-api:8000")

_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _schema_to_pydantic(tool_name: str, params: dict) -> type[BaseModel] | None:
    """Convert a JSON Schema 'properties' block into a dynamic Pydantic model."""
    props = params.get("properties", {})
    required = set(params.get("required", []))
    if not props:
        return None
    fields: dict = {}
    for pname, pdef in props.items():
        py_type = _TYPE_MAP.get(pdef.get("type", "string"), str)
        desc = pdef.get("description", "")
        if pname in required:
            fields[pname] = (py_type, Field(description=desc))
        else:
            fields[pname] = (Optional[py_type], Field(default=pdef.get("default"), description=desc))
    return create_model(f"{tool_name}_Input", **fields)


def build_tools(
    tools_schema: list[dict],
    media_collector: list[dict],
    api_url: str | None = None,
    agent_context: dict | None = None,
) -> list[StructuredTool]:
    """Create LangChain StructuredTool instances from OpenAI function-calling schemas.

    Each tool calls POST {api_url}/api/tools/execute.  Any media items returned
    by the API (e.g. from send_media) are appended to ``media_collector``.
    """
    base = api_url or API_URL
    tools: list[StructuredTool] = []

    for schema in tools_schema:
        fn = schema["function"]
        name = fn["name"]
        desc = fn["description"]
        params = fn.get("parameters", {"type": "object", "properties": {}})
        args_model = _schema_to_pydantic(name, params)

        async def _execute(__tool_name=name, __ctx=agent_context, __media=media_collector, **kwargs):
            payload: dict = {"tool_name": __tool_name, "arguments": kwargs}
            if __ctx:
                payload["agent_context"] = __ctx
            async with httpx.AsyncClient(base_url=base, timeout=60) as client:
                res = await client.post("/api/tools/execute", json=payload)
                if res.status_code == 200:
                    data = res.json()
                    for item in data.get("media", []):
                        __media.append(item)
                    return data.get("result", "No result returned")
                return f"Tool error ({res.status_code}): {res.text[:300]}"

        tool = StructuredTool.from_function(
            coroutine=_execute,
            name=name,
            description=desc,
            args_schema=args_model,
        )
        tools.append(tool)

    return tools
