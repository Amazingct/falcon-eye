"""Tool handler implementations - execute tools by calling internal APIs"""
import asyncio
import base64
import json
import os
import re
import tempfile
import httpx
from app.config import get_settings

settings = get_settings()
API_BASE = f"http://localhost:{settings.port}"


async def _api_get(path: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get(f"{API_BASE}{path}")
        return res.json()


async def _api_post(path: str, data: dict = None) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(f"{API_BASE}{path}", json=data)
        return res.json()


async def list_cameras(**kwargs) -> str:
    result = await _api_get("/api/cameras/")
    cameras = result.get("cameras", [])
    summary = []
    for c in cameras:
        summary.append(f"- {c['name']} ({c['protocol']}) on {c.get('node_name', 'N/A')} — {c['status']}")
    return f"Found {len(cameras)} cameras:\n" + "\n".join(summary) if summary else "No cameras found."


async def camera_status(camera_id: str, **kwargs) -> str:
    try:
        result = await _api_get(f"/api/cameras/{camera_id}")
        return f"Camera '{result['name']}' is {result['status']} (protocol: {result['protocol']}, node: {result.get('node_name', 'N/A')})"
    except Exception as e:
        return f"Error checking camera status: {e}"


async def control_camera(camera_id: str, action: str, **kwargs) -> str:
    try:
        result = await _api_post(f"/api/cameras/{camera_id}/{action}")
        return f"Camera {action} result: {result.get('message', 'OK')}"
    except Exception as e:
        return f"Error controlling camera: {e}"


async def camera_snapshot(camera_id: str, **kwargs) -> str:
    return f"Snapshot functionality not yet implemented for camera {camera_id}. Use the stream URL to view the camera."


async def start_recording(camera_id: str, **kwargs) -> str:
    try:
        result = await _api_post(f"/api/cameras/{camera_id}/recording/start")
        return f"Recording started: {json.dumps(result)}"
    except Exception as e:
        return f"Error starting recording: {e}"


async def stop_recording(camera_id: str, **kwargs) -> str:
    try:
        result = await _api_post(f"/api/cameras/{camera_id}/recording/stop")
        return f"Recording stopped: {json.dumps(result)}"
    except Exception as e:
        return f"Error stopping recording: {e}"


async def list_recordings(camera_id: str = None, **kwargs) -> str:
    path = "/api/recordings/"
    if camera_id:
        path += f"?camera_id={camera_id}"
    result = await _api_get(path)
    recs = result.get("recordings", [])
    if not recs:
        return "No recordings found."
    summary = []
    for r in recs:
        dur = f"{r.get('duration_seconds', '?')}s" if r.get("duration_seconds") else "in progress"
        summary.append(f"- {r['file_name']} ({r['status']}, {dur})")
    return f"Found {len(recs)} recordings:\n" + "\n".join(summary)


async def list_nodes(**kwargs) -> str:
    result = await _api_get("/api/nodes/")
    if not result:
        return "No nodes found."
    summary = []
    for n in result:
        status = "Ready" if n.get("ready") else "NotReady"
        summary.append(f"- {n['name']} ({n.get('ip', 'N/A')}) — {status}")
    return f"Found {len(result)} nodes:\n" + "\n".join(summary)


async def scan_cameras(network: bool = True, **kwargs) -> str:
    path = f"/api/nodes/scan/cameras?network={'true' if network else 'false'}"
    result = await _api_get(path)
    usb = result.get("cameras", [])
    net = result.get("network_cameras", [])
    parts = []
    if usb:
        parts.append(f"USB cameras: {len(usb)}")
        for c in usb:
            parts.append(f"  - {c.get('device_name', 'Unknown')} on {c['node_name']} ({c['device_path']})")
    if net:
        parts.append(f"Network cameras: {len(net)}")
        for c in net:
            parts.append(f"  - {c.get('name', 'Unknown')} at {c.get('url', c.get('ip', 'N/A'))}")
    return "\n".join(parts) if parts else "No cameras found during scan."


async def system_info(**kwargs) -> str:
    nodes = await _api_get("/api/nodes/")
    cameras = await _api_get("/api/cameras/")
    cam_list = cameras.get("cameras", [])
    running = sum(1 for c in cam_list if c["status"] == "running")
    return (
        f"System Info:\n"
        f"- Nodes: {len(nodes)}\n"
        f"- Cameras: {len(cam_list)} total, {running} running\n"
        f"- Namespace: {settings.k8s_namespace}"
    )


async def send_alert(message: str, severity: str = "info", **kwargs) -> str:
    return f"Alert [{severity.upper()}]: {message} (Alert delivery not yet configured)"


async def web_search(query: str, **kwargs) -> str:
    return f"Web search not yet implemented. Query was: {query}"


async def spawn_agent(name: str, type: str, provider: str, model: str, system_prompt: str = None, tools: list = None, **kwargs) -> str:
    """Create and start a new agent"""
    try:
        slug = re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")[:50]
        payload = {
            "name": name,
            "slug": slug,
            "type": "pod",
            "provider": provider,
            "model": model,
            "channel_type": type,
            "system_prompt": system_prompt or f"You are {name}, a Falcon-Eye agent.",
            "tools": tools or [],
        }
        result = await _api_post("/api/agents/", payload)
        agent_id = result.get("id")
        if not agent_id:
            return f"Failed to create agent: {json.dumps(result)}"
        # Start the agent
        start_result = await _api_post(f"/api/agents/{agent_id}/start")
        return f"Agent '{name}' created (id: {agent_id}) and started. {start_result.get('message', '')}"
    except Exception as e:
        return f"Error spawning agent: {e}"


async def clone_agent(source_agent_id: str, new_name: str, override_system_prompt: str = None, override_tools: list = None, **kwargs) -> str:
    """Clone an existing agent's configuration into a new agent"""
    try:
        source = await _api_get(f"/api/agents/{source_agent_id}")
        if "detail" in source:
            return f"Source agent not found: {source.get('detail')}"

        slug = re.sub(r"[^a-z0-9-]", "-", new_name.lower()).strip("-")[:50]
        payload = {
            "name": new_name,
            "slug": slug,
            "type": source.get("type", "pod"),
            "provider": source["provider"],
            "model": source["model"],
            "api_key_ref": source.get("api_key_ref"),
            "system_prompt": override_system_prompt or source.get("system_prompt"),
            "temperature": source.get("temperature", 0.7),
            "max_tokens": source.get("max_tokens", 4096),
            "channel_type": source.get("channel_type"),
            "channel_config": source.get("channel_config", {}),
            "tools": override_tools if override_tools is not None else source.get("tools", []),
            "cpu_limit": source.get("cpu_limit", "500m"),
            "memory_limit": source.get("memory_limit", "512Mi"),
        }
        result = await _api_post("/api/agents/", payload)
        return f"Agent '{new_name}' cloned from '{source['name']}' (new id: {result.get('id')})"
    except Exception as e:
        return f"Error cloning agent: {e}"


async def analyze_camera(camera_id: str, mode: str = "snapshot", duration: int = 3, **kwargs) -> str:
    """Capture frame(s) from a camera and analyze with vision AI.

    The ``_agent_context`` kwarg is injected by the chat route so we
    can use the calling agent's own LLM credentials for the vision call.
    """
    agent_ctx = kwargs.get("_agent_context", {})

    # 1. Resolve stream URL
    try:
        cam = await _api_get(f"/api/cameras/{camera_id}")
        if cam.get("status") != "running":
            return f"Camera '{cam.get('name', camera_id)}' is not running (status: {cam.get('status')})"

        # Build the internal stream URL (same logic as recorder)
        svc_name = cam.get("service_name")
        if not svc_name:
            return "Camera has no service — cannot capture."
        stream_url = f"http://{svc_name}.{settings.k8s_namespace}.svc.cluster.local:8081/"

        # For RTSP cameras, prefer the source_url for ffmpeg (better quality)
        if cam.get("protocol") in ("rtsp", "onvif") and cam.get("source_url"):
            stream_url = cam["source_url"]
    except Exception as e:
        return f"Error resolving camera stream: {e}"

    # 2. Capture with ffmpeg
    tmp_dir = tempfile.mkdtemp(prefix="fe-analyze-")
    image_paths: list[str] = []

    try:
        if mode == "clip":
            duration = max(3, min(5, duration))
            # Capture a short clip then extract frames
            clip_path = os.path.join(tmp_dir, "clip.mp4")
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-i", stream_url,
                "-t", str(duration),
                "-an",  # no audio
                "-vf", f"fps=1",  # 1 frame per second → 3-5 frames
                os.path.join(tmp_dir, "frame_%02d.jpg"),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=duration + 15)
            if proc.returncode != 0:
                return f"ffmpeg frame extraction failed: {stderr.decode()[-300:]}"
            # Gather extracted frames
            for f in sorted(os.listdir(tmp_dir)):
                if f.startswith("frame_") and f.endswith(".jpg"):
                    image_paths.append(os.path.join(tmp_dir, f))
            if not image_paths:
                return "ffmpeg produced no frames from the clip."
        else:
            # Single snapshot
            out_path = os.path.join(tmp_dir, "snapshot.jpg")
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-i", stream_url,
                "-frames:v", "1",
                "-q:v", "2",
                out_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode != 0:
                return f"ffmpeg snapshot failed: {stderr.decode()[-300:]}"
            if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
                return "ffmpeg produced an empty snapshot."
            image_paths.append(out_path)

        # 3. Encode images to base64
        b64_images: list[str] = []
        for p in image_paths:
            with open(p, "rb") as fh:
                b64_images.append(base64.b64encode(fh.read()).decode())

        # 4. Send to vision LLM
        provider = agent_ctx.get("provider", "openai")
        model = agent_ctx.get("model", "gpt-4o")
        api_key = agent_ctx.get("api_key") or os.getenv("ANTHROPIC_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
        cam_name = cam.get("name", camera_id)
        vision_prompt = (
            f"This is a live feed from security camera '{cam_name}'. "
            "Describe what you see. Note any people, activity, objects, or anything unusual."
        )

        if provider == "anthropic":
            description = await _vision_anthropic(api_key, model, b64_images, vision_prompt)
        else:
            base_url = "https://api.openai.com/v1" if provider == "openai" else "http://ollama:11434/v1"
            description = await _vision_openai(api_key, model, base_url, b64_images, vision_prompt)

        return f"[Camera: {cam_name} | Mode: {mode}]\n{description}"

    except asyncio.TimeoutError:
        return "ffmpeg timed out while capturing from the camera stream."
    except Exception as e:
        return f"Error during camera analysis: {e}"
    finally:
        # Cleanup temp files
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def _vision_openai(api_key: str, model: str, base_url: str, b64_images: list[str], prompt: str) -> str:
    """Send images to an OpenAI-compatible vision endpoint."""
    content: list[dict] = [{"type": "text", "text": prompt}]
    for img in b64_images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{img}", "detail": "low"},
        })

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 1024,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
        if res.status_code != 200:
            return f"Vision API error ({res.status_code}): {res.text[:500]}"
        data = res.json()
        return data["choices"][0]["message"].get("content", "")


async def _vision_anthropic(api_key: str, model: str, b64_images: list[str], prompt: str) -> str:
    """Send images to Anthropic's messages API with vision."""
    if not api_key:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "Anthropic API key not configured — cannot run vision analysis."

    content: list[dict] = []
    for img in b64_images:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": img},
        })
    content.append({"type": "text", "text": prompt})

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 1024,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
        if res.status_code != 200:
            return f"Anthropic vision error ({res.status_code}): {res.text[:500]}"
        data = res.json()
        text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
        return " ".join(text_blocks) if text_blocks else "(no description returned)"


async def custom_api_call(url: str, method: str = "GET", body: str = None, **kwargs) -> str:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if method == "GET":
                res = await client.get(url)
            elif method == "POST":
                res = await client.post(url, content=body, headers={"Content-Type": "application/json"})
            elif method == "PUT":
                res = await client.put(url, content=body, headers={"Content-Type": "application/json"})
            elif method == "DELETE":
                res = await client.delete(url)
            else:
                return f"Unsupported method: {method}"
            return f"Response ({res.status_code}): {res.text[:1000]}"
    except Exception as e:
        return f"API call error: {e}"


# Map handler names to functions
HANDLER_MAP = {
    "app.tools.handlers.list_cameras": list_cameras,
    "app.tools.handlers.camera_status": camera_status,
    "app.tools.handlers.control_camera": control_camera,
    "app.tools.handlers.camera_snapshot": camera_snapshot,
    "app.tools.handlers.start_recording": start_recording,
    "app.tools.handlers.stop_recording": stop_recording,
    "app.tools.handlers.list_recordings": list_recordings,
    "app.tools.handlers.list_nodes": list_nodes,
    "app.tools.handlers.scan_cameras": scan_cameras,
    "app.tools.handlers.system_info": system_info,
    "app.tools.handlers.send_alert": send_alert,
    "app.tools.handlers.web_search": web_search,
    "app.tools.handlers.custom_api_call": custom_api_call,
    "app.tools.handlers.spawn_agent": spawn_agent,
    "app.tools.handlers.clone_agent": clone_agent,
    "app.tools.handlers.analyze_camera": analyze_camera,
}


async def execute_tool(tool_name: str, arguments: dict, agent_context: dict | None = None) -> str:
    """Execute a tool by its function name.

    ``agent_context`` carries the calling agent's LLM config so tools like
    ``analyze_camera`` can make vision calls with the agent's own credentials.
    """
    from app.tools.registry import TOOLS_REGISTRY

    # Inject agent context for handlers that need it
    if agent_context:
        arguments = {**arguments, "_agent_context": agent_context}

    # Find tool by function name
    for tool_id, tool in TOOLS_REGISTRY.items():
        if tool["name"] == tool_name:
            handler_path = tool["handler"]
            handler = HANDLER_MAP.get(handler_path)
            if handler:
                return await handler(**arguments)
            return f"Handler not found: {handler_path}"
    return f"Unknown tool: {tool_name}"
