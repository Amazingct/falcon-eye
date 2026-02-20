"""Unified async LLM client supporting OpenAI, Anthropic, and Ollama"""
import json
from typing import Optional


async def chat(
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> dict:
    """
    Unified LLM chat call.
    Returns: {"content": str, "tool_calls": list|None, "usage": dict}
    """
    if provider == "anthropic":
        return await _call_anthropic(api_key, model, messages, tools, max_tokens, temperature)
    else:
        # OpenAI and Ollama (OpenAI-compatible)
        if provider == "ollama":
            effective_base = base_url or "http://ollama:11434/v1"
        else:
            effective_base = base_url or "https://api.openai.com/v1"
        return await _call_openai(api_key, model, effective_base, messages, tools, max_tokens, temperature)


async def _call_openai(api_key, model, base_url, messages, tools, max_tokens, temperature) -> dict:
    import httpx

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools

    async with httpx.AsyncClient(timeout=120) as client:
        res = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
        if res.status_code != 200:
            raise Exception(f"LLM API error ({res.status_code}): {res.text[:500]}")
        data = res.json()

    choice = data["choices"][0]
    msg = choice["message"]
    usage = data.get("usage", {})

    tool_calls = None
    if msg.get("tool_calls"):
        tool_calls = []
        for tc in msg["tool_calls"]:
            try:
                args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({
                "id": tc["id"],
                "name": tc["function"]["name"],
                "arguments": args,
            })

    return {
        "content": msg.get("content", ""),
        "tool_calls": tool_calls,
        "raw_message": msg,
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
        },
    }


async def _call_anthropic(api_key, model, messages, tools, max_tokens, temperature) -> dict:
    import httpx

    if not api_key:
        raise Exception("Anthropic API key not configured")

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }

    # Convert to Anthropic format
    system_prompt = None
    anthropic_messages = []
    for m in messages:
        if m["role"] == "system":
            system_prompt = m["content"]
        else:
            anthropic_messages.append({"role": m["role"], "content": m["content"]})

    anthropic_tools = []
    for t in (tools or []):
        fn = t["function"]
        anthropic_tools.append({
            "name": fn["name"],
            "description": fn["description"],
            "input_schema": fn["parameters"],
        })

    payload = {
        "model": model,
        "messages": anthropic_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if system_prompt:
        payload["system"] = system_prompt
    if anthropic_tools:
        payload["tools"] = anthropic_tools

    async with httpx.AsyncClient(timeout=120) as client:
        res = await client.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
        if res.status_code != 200:
            raise Exception(f"Anthropic API error ({res.status_code}): {res.text[:500]}")
        data = res.json()

    usage = data.get("usage", {})
    tool_use_blocks = [b for b in data.get("content", []) if b["type"] == "tool_use"]
    text_blocks = [b for b in data.get("content", []) if b["type"] == "text"]

    tool_calls = None
    if tool_use_blocks and data.get("stop_reason") == "tool_use":
        tool_calls = []
        for tu in tool_use_blocks:
            tool_calls.append({
                "id": tu["id"],
                "name": tu["name"],
                "arguments": tu.get("input", {}),
            })

    content = " ".join(b["text"] for b in text_blocks) if text_blocks else ""

    return {
        "content": content,
        "tool_calls": tool_calls,
        "raw_content": data.get("content", []),
        "usage": {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
        },
    }
