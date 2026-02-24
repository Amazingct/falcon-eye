"""Tool handler implementations - execute tools by calling internal APIs"""
import asyncio
import base64
import json
import logging
import os
import re
import uuid as _uuid
from urllib.parse import quote
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
import os as _os
API_BASE = f"http://localhost:{settings.port}"
_INTERNAL_KEY = _os.environ.get("INTERNAL_API_KEY", "")
_INTERNAL_HEADERS = {"X-Internal-Key": _INTERNAL_KEY} if _INTERNAL_KEY else {}

# Tools that ephemeral (task-based) agents must NOT inherit, to prevent
# recursive spawning loops and unintended scheduling side-effects.
EPHEMERAL_EXCLUDED_TOOLS = {
    "agent_spawn", "agent_delegate", "agent_clone",
    "cron_create", "cron_list", "cron_delete",
}


async def _api_get(path: str) -> dict:
    async with httpx.AsyncClient(timeout=30, headers=_INTERNAL_HEADERS) as client:
        res = await client.get(f"{API_BASE}{path}")
        if res.status_code >= 400:
            raise Exception(f"API GET {path} returned {res.status_code}: {res.text[:300]}")
        return res.json()


async def _api_post(path: str, data: dict = None) -> dict:
    async with httpx.AsyncClient(timeout=30, headers=_INTERNAL_HEADERS) as client:
        res = await client.post(f"{API_BASE}{path}", json=data)
        if res.status_code >= 400:
            raise Exception(f"API POST {path} returned {res.status_code}: {res.text[:300]}")
        return res.json()


async def list_cameras(**kwargs) -> str:
    result = await _api_get("/api/cameras/")
    cameras = result.get("cameras", [])
    if not cameras:
        return "No cameras found."
    summary = []
    for c in cameras:
        summary.append(
            f"- **{c['name']}** (id: `{c['id']}`) — {c['status']} | "
            f"{c['protocol']} on {c.get('node_name', 'N/A')}"
        )
    return f"Found {len(cameras)} cameras:\n" + "\n".join(summary)


async def _resolve_camera_id(camera_id: str) -> str:
    """Resolve a camera name/slug to UUID if needed."""
    # If it looks like a UUID, return as-is
    if len(camera_id) == 36 and "-" in camera_id:
        return camera_id
    # Otherwise search by name
    result = await _api_get("/api/cameras/")
    for cam in result.get("cameras", []):
        if camera_id.lower() in cam["name"].lower() or camera_id.lower() in cam.get("deployment_name", "").lower():
            return str(cam["id"])
    return camera_id  # fallback


async def camera_status(camera_id: str, **kwargs) -> str:
    try:
        resolved = await _resolve_camera_id(camera_id)
        result = await _api_get(f"/api/cameras/{resolved}")
        return f"Camera '{result['name']}' (id: {result['id']}) is {result['status']} (protocol: {result['protocol']}, node: {result.get('node_name', 'N/A')})"
    except Exception as e:
        return f"Error checking camera status: {e}"


async def control_camera(camera_id: str, action: str, **kwargs) -> str:
    try:
        camera_id = await _resolve_camera_id(camera_id)
        result = await _api_post(f"/api/cameras/{camera_id}/{action}")
        return f"Camera {action} result: {result.get('message', 'OK')}"
    except Exception as e:
        return f"Error controlling camera: {e}"


async def camera_snapshot(camera_id: str, **kwargs) -> str:
    camera_id = await _resolve_camera_id(camera_id)
    """Grab a single JPEG frame from a camera's MJPEG stream and save to filesystem."""
    import time

    try:
        camera = await _api_get(f"/api/cameras/{camera_id}")
    except Exception as e:
        return f"Error: camera {camera_id} not found ({e})"

    service_name = camera.get("service_name")
    if not service_name:
        return f"Camera '{camera.get('name', camera_id)}' is not running. Start it first."

    stream_url = (
        f"http://{service_name}"
        f".{settings.k8s_namespace}.svc.cluster.local:8081/"
    )

    # Grab one JPEG frame from the MJPEG stream
    try:
        frame = None
        async with httpx.AsyncClient(timeout=10) as client:
            async with client.stream("GET", stream_url) as resp:
                buf = b""
                async for chunk in resp.aiter_bytes(chunk_size=8192):
                    buf += chunk
                    start = buf.find(b"\xff\xd8")
                    if start == -1:
                        continue
                    end = buf.find(b"\xff\xd9", start)
                    if end != -1:
                        frame = buf[start : end + 2]
                        break
        if not frame:
            return "Could not capture a frame from the camera stream."
    except httpx.TimeoutException:
        return f"Camera stream timed out. Ensure camera '{camera.get('name', camera_id)}' is running."
    except Exception as e:
        return f"Error capturing frame: {e}"

    # Save to shared filesystem via upload endpoint
    cam_slug = re.sub(r"[^a-z0-9]+", "_", camera.get("name", "cam").lower()).strip("_")
    filename = f"snapshots/{cam_slug}_{int(time.time())}.jpg"

    try:
        async with httpx.AsyncClient(timeout=15, headers=_INTERNAL_HEADERS) as client:
            resp = await client.post(
                f"{API_BASE}/api/files/upload/{filename}",
                files={"file": (os.path.basename(filename), frame, "image/jpeg")},
            )
            if resp.status_code != 200:
                return f"Failed to save snapshot: {resp.text[:200]}"
    except Exception as e:
        return f"Error saving snapshot: {e}"

    return f"Snapshot saved: {filename} ({len(frame)} bytes). Use send_media to deliver it to the user."


async def start_recording(camera_id: str, **kwargs) -> str:
    camera_id = await _resolve_camera_id(camera_id)
    try:
        result = await _api_post(f"/api/cameras/{camera_id}/recording/start")
        return f"Recording started: {json.dumps(result)}"
    except Exception as e:
        return f"Error starting recording: {e}"


async def stop_recording(camera_id: str, **kwargs) -> str:
    camera_id = await _resolve_camera_id(camera_id)
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
        cloud = " ☁️" if r.get("cloud_url") else ""
        summary.append(f"- {r['file_name']} ({r['status']}, {dur}{cloud}) [id: {r['id']}]")
    return f"Found {len(recs)} recordings:\n" + "\n".join(summary) + "\n\n⚠️ IMPORTANT: To send a recording to the user, you MUST call the send_recording tool with the recording id. Do NOT share URLs directly — the user needs the video delivered inline."


async def get_recording(recording_id: str, **kwargs) -> str:
    """Get full details and download URL for a specific recording."""
    try:
        result = await _api_get(f"/api/recordings/{recording_id}")
        dl_url = f"/api/recordings/{recording_id}/download"
        camera_info = result.get("camera_info") or {}
        camera_name = camera_info.get("name", result.get("camera_id", "unknown"))
        node = camera_info.get("node_name", result.get("node_name", "N/A"))
        file_size = result.get("file_size_bytes")
        size_str = f"{file_size / 1024 / 1024:.1f}MB" if file_size else "unknown"

        return (
            f"Recording: {result.get('file_name', 'unknown')}\n"
            f"ID: {result.get('id', recording_id)}\n"
            f"Camera: {camera_name}\n"
            f"Node: {node}\n"
            f"Status: {result.get('status', 'unknown')}\n"
            f"Start: {result.get('start_time', 'N/A')}\n"
            f"End: {result.get('end_time', 'N/A')}\n"
            f"Duration: {result.get('duration_seconds', '?')}s\n"
            f"File size: {size_str}\n"
            f"Resolution: {result.get('resolution', 'N/A')}\n"
            f"Storage: {'cloud' if result.get('cloud_url') else 'local'}\n"
            f"Created: {result.get('created_at', 'N/A')}\n\n"
            f"⚠️ To deliver this recording to the user, you MUST call send_recording with recording_id='{recording_id}'. Do NOT share any URLs — send_recording handles the download and inline delivery automatically."
        )
    except Exception as e:
        return f"Error getting recording: {e}"


async def send_recording(recording_id: str, caption: str = "", **kwargs) -> str:
    """Send a recording to the user as an inline video.
    Accepts either a recording ID or a filename — resolves to the correct download URL."""
    try:
        # If it looks like a filename, search recordings to find the ID
        if "." in recording_id and not recording_id.startswith("/"):
            result = await _api_get("/api/recordings/")
            recs = result.get("recordings", [])
            match = None
            for r in recs:
                if r.get("file_name") == recording_id or recording_id in (r.get("file_name") or ""):
                    match = r
                    break
            if not match:
                return f"Recording not found: {recording_id}"
            recording_id = match["id"]
            if not caption:
                dur = match.get("duration_seconds", "?")
                camera = match.get("camera_name") or "camera"
                caption = f"{match['file_name']} ({dur}s) — {camera}"

        # Verify the recording exists
        rec = await _api_get(f"/api/recordings/{recording_id}")
        dl_url = f"/api/recordings/{recording_id}/download"

        if not caption:
            dur = rec.get("duration_seconds", "?")
            camera = rec.get("camera_name") or "camera"
            caption = f"{rec.get('file_name', 'recording')} ({dur}s) — {camera}"

        # Queue it as video media — include cloud_url and file_path so the
        # agent can download directly if the API proxy times out.
        media_entry = {
            "path": dl_url,
            "url": dl_url,
            "cloud_url": rec.get("cloud_url"),
            "file_path": rec.get("file_path"),
            "caption": caption,
            "media_type": "video",
            "size": rec.get("file_size_bytes"),
            "mime_type": "video/mp4",
        }

        ctx = kwargs.get("_agent_context", {})
        if "pending_media" in ctx:
            ctx["pending_media"].append(media_entry)
            return f"Sent recording: {rec.get('file_name', recording_id)} ({rec.get('duration_seconds', '?')}s)"
        else:
            return f"Recording queued for delivery but media queue was unavailable. The system will retry. Tell the user the recording is being sent and to wait a moment."

    except Exception as e:
        return f"Error sending recording: {e}"


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
    """Send an alert: logs to the filesystem and pushes to Telegram agents if any exist."""
    import time
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    log_line = f"[{timestamp}] [{severity.upper()}] {message}"

    # Append to alerts log on the shared filesystem
    try:
        await _api_post("/api/files/write", {
            "path": "alerts/alerts.log",
            "content": log_line + "\n",
            "append": True,
        })
    except Exception:
        pass

    # Try to push to Telegram-connected agents
    delivered_to = []
    try:
        agents_res = await _api_get("/api/agents/")
        for agent in agents_res.get("agents", []):
            if agent.get("channel_type") == "telegram" and agent.get("status") == "running":
                cfg = agent.get("channel_config") or {}
                bot_token = cfg.get("bot_token")
                chat_id = cfg.get("chat_id")
                if bot_token and chat_id:
                    emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(severity, "📢")
                    text = f"{emoji} **Falcon-Eye Alert** [{severity.upper()}]\n\n{message}"
                    try:
                        async with httpx.AsyncClient(timeout=10) as client:
                            await client.post(
                                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                                json={"chat_id": chat_id, "text": text},
                            )
                        delivered_to.append(f"Telegram ({agent['name']})")
                    except Exception:
                        pass
    except Exception:
        pass

    parts = [f"Alert logged: {log_line}"]
    if delivered_to:
        parts.append(f"Delivered to: {', '.join(delivered_to)}")
    else:
        parts.append("No Telegram channels available for push delivery.")
    return " | ".join(parts)


async def web_search(query: str, **kwargs) -> str:
    """Search the web using DuckDuckGo and return top results."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            res = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (compatible; FalconEye/1.0)"},
            )
            if res.status_code != 200:
                return f"Search request failed ({res.status_code})"

            results = []
            for match in re.finditer(
                r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>'
                r'.*?class="result__snippet"[^>]*>(.*?)</(?:span|div)',
                res.text,
                re.DOTALL,
            ):
                url, title, snippet = match.groups()
                title = re.sub(r"<[^>]+>", "", title).strip()
                snippet = re.sub(r"<[^>]+>", "", snippet).strip()
                if title and snippet:
                    results.append(f"- **{title}**\n  {snippet}\n  {url}")
                if len(results) >= 5:
                    break

            if results:
                return f"Search results for '{query}':\n\n" + "\n\n".join(results)

            # Fallback: try DuckDuckGo instant answer API
            res2 = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": "1"},
            )
            data = res2.json()
            abstract = data.get("AbstractText", "")
            if abstract:
                return f"Summary: {abstract}\nSource: {data.get('AbstractSource', '')}"

            return f"No results found for '{query}'."
    except Exception as e:
        return f"Search error: {e}"


async def spawn_agent(name: str, system_prompt: str = None, tools: list = None,
                      channel_type: str = None, task: str = None, **kwargs) -> str:
    """Create and start a new agent. Automatically inherits the calling agent's
    LLM config. If ``task`` is provided the agent runs as a K8s Job
    (run-to-completion, no restart). The result is posted back to the caller's
    session once the Job finishes, and the ephemeral agent is auto-cleaned."""
    try:
        agent_ctx = kwargs.get("_agent_context", {})
        parent_agent_id = agent_ctx.get("agent_id")
        caller_session_id = agent_ctx.get("session_id")

        parent_config = {}
        if parent_agent_id:
            try:
                parent_config = await _api_get(f"/api/agents/{parent_agent_id}")
            except Exception:
                pass

        # Unique slug to prevent 409 collisions on repeated spawns
        short_id = str(_uuid.uuid4())[:8]
        slug = re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")[:40]
        slug = f"{slug}-{short_id}"

        # For ephemeral (task) agents, strip out meta-tools that could cause loops
        parent_tools = tools if tools is not None else parent_config.get("tools", [])
        agent_tools = (
            [t for t in parent_tools if t not in EPHEMERAL_EXCLUDED_TOOLS]
            if task else parent_tools
        )

        payload = {
            "name": name,
            "slug": slug,
            "type": "pod",
            "provider": parent_config.get("provider", agent_ctx.get("provider", "openai")),
            "model": parent_config.get("model", agent_ctx.get("model", "gpt-4o")),
            "api_key_ref": parent_config.get("api_key_ref"),
            "temperature": parent_config.get("temperature", 0.7),
            "max_tokens": parent_config.get("max_tokens", 4096),
            "cpu_limit": parent_config.get("cpu_limit", "500m"),
            "memory_limit": parent_config.get("memory_limit", "512Mi"),
            "channel_type": None if task else (channel_type or parent_config.get("channel_type")),
            "channel_config": {} if task else parent_config.get("channel_config", {}),
            "system_prompt": system_prompt or (
                f"You are {name}, a specialized Falcon-Eye agent. "
                f"Complete the assigned task thoroughly but efficiently. "
                f"Limit tool calls — gather essential information in a few "
                f"focused steps, then produce your final answer."
            ),
            "tools": agent_tools,
        }
        result = await _api_post("/api/agents/", payload)
        agent_id = result.get("id")
        if not agent_id:
            return f"Failed to create agent: {json.dumps(result)}"

        if not task:
            # Persistent agent — create K8s Deployment (long-running)
            start_result = await _api_post(f"/api/agents/{agent_id}/start")
            return (
                f"Agent '{name}' created (id: {agent_id}) and started. "
                f"Inherited config from parent agent. {start_result.get('message', '')}"
            )

        # Ephemeral agent with task — create K8s Job (run once, callback, exit)
        start_result = await _api_post(f"/api/agents/{agent_id}/start-task", {
            "task": task,
            "caller_agent_id": parent_agent_id,
            "caller_session_id": caller_session_id,
        })

        return (
            f"Agent '{name}' has been spawned (id: {agent_id}) and is executing the task "
            f"as a background Job. You will receive the result once it completes. "
            f"Continue with other work in the meantime."
        )
    except Exception as e:
        return f"Error spawning agent: {e}"


async def delegate_task(agent_id: str, task: str, **kwargs) -> str:
    """Send a task to an already-running agent asynchronously.
    Returns immediately — the result is posted back to the caller's session
    as a system message once the target agent completes."""
    agent_ctx = kwargs.get("_agent_context", {})
    caller_agent_id = agent_ctx.get("agent_id")
    caller_session_id = agent_ctx.get("session_id")

    try:
        agent = await _api_get(f"/api/agents/{agent_id}")
        agent_name = agent.get("name", agent_id)
        if agent.get("status") != "running":
            return (
                f"Agent '{agent_name}' is not running (status: {agent.get('status')}). "
                "Start it first or use spawn_agent with a task."
            )

        asyncio.create_task(
            _background_delegate_task(
                agent_id=agent_id,
                agent_name=agent_name,
                task=task,
                caller_agent_id=caller_agent_id,
                caller_session_id=caller_session_id,
            )
        )

        return (
            f"Task has been delegated to agent '{agent_name}' (id: {agent_id}). "
            f"It is running in the background. You will receive the result as a "
            f"system message once it completes. Continue with other work."
        )
    except Exception as e:
        return f"Error delegating task: {e}"


# ---------------------------------------------------------------------------
#  Background task helpers
# ---------------------------------------------------------------------------

async def _background_delegate_task(
    agent_id: str,
    agent_name: str,
    task: str,
    caller_agent_id: str | None,
    caller_session_id: str | None,
):
    """Run in background after delegate_task returns. Sends the task to the
    already-running target agent and delivers the result to the caller agent."""
    try:
        task_response = await _wait_and_send_task(
            agent_id, task, source_user=caller_agent_id, retries=1,
        )

        if caller_agent_id and caller_session_id:
            await _retrigger_caller(caller_agent_id, caller_session_id, agent_name, task_response)
    except Exception as exc:
        logger.error("Background delegate task failed for agent %s: %s", agent_id, exc)
        if caller_agent_id and caller_session_id:
            await _retrigger_caller(
                caller_agent_id, caller_session_id, agent_name,
                f"(delegated task failed: {exc})",
            )


async def _wait_and_send_task(agent_id: str, task: str,
                              source_user: str | None = None,
                              retries: int = 20) -> str:
    """Poll the agent until it's reachable, then send a task via the chat API."""
    last_error = ""
    for attempt in range(retries):
        try:
            result = await _api_post(f"/api/chat/{agent_id}/send", {
                "message": task,
                "source": "agent",
                "source_user": source_user,
            })
            return result.get("response", "(no response)")
        except Exception as e:
            last_error = str(e)
            if attempt < retries - 1:
                await asyncio.sleep(3)

    return f"(agent did not respond after {retries} attempts — last error: {last_error})"


async def _retrigger_caller(caller_agent_id: str, caller_session_id: str,
                             agent_name: str, task_response: str):
    """Re-invoke the caller agent with the completed task result.

    The result is delivered as a single *user* message (not a system message)
    so that LangGraph doesn't reject it for having non-consecutive system
    messages in the conversation history."""
    try:
        result = await _api_post(f"/api/chat/{caller_agent_id}/send", {
            "message": (
                f"[Automated callback — the agent '{agent_name}' you dispatched "
                f"has completed its task. Here is the result:]\n\n"
                f"{task_response}\n\n"
                f"[Please review the result above and relay the key findings "
                f"to the user. Do NOT spawn another agent for this — "
                f"just summarize the result and respond directly.]"
            ),
            "session_id": caller_session_id,
            "source": "agent",
            "source_user": agent_name,
        })
        response_text = result.get("response", "")

        if response_text:
            await _try_push_telegram(caller_agent_id, response_text)
    except Exception as exc:
        logger.warning("Failed to re-trigger caller agent %s: %s", caller_agent_id, exc)


async def _try_push_telegram(agent_id: str, message: str):
    """If the agent has Telegram configured with a chat_id, push the message."""
    try:
        agent = await _api_get(f"/api/agents/{agent_id}")
        if agent.get("channel_type") == "telegram":
            cfg = agent.get("channel_config") or {}
            bot_token = cfg.get("bot_token")
            chat_id = cfg.get("chat_id")
            if bot_token and chat_id:
                async with httpx.AsyncClient(timeout=15) as client:
                    await client.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
                    )
    except Exception:
        pass


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


async def create_cron_job(name: str, cron_expr: str, prompt: str,
                          timezone: str = "UTC", timeout_seconds: int = 120,
                          **kwargs) -> str:
    """Create a scheduled cron job that sends a prompt to this agent on a
    recurring schedule. The cron results are delivered to the caller's current
    chat session so the conversation stays continuous."""
    agent_ctx = kwargs.get("_agent_context", {})
    agent_id = agent_ctx.get("agent_id")
    session_id = agent_ctx.get("session_id")

    if not agent_id:
        return "Cannot create cron job: agent context not available."

    try:
        payload = {
            "name": name,
            "agent_id": agent_id,
            "cron_expr": cron_expr,
            "timezone": timezone,
            "session_id": session_id,
            "prompt": prompt,
            "timeout_seconds": timeout_seconds,
            "enabled": True,
        }
        result = await _api_post("/api/cron/", payload)
        cron_id = result.get("id", "unknown")
        return (
            f"Cron job '{name}' created (id: {cron_id}).\n"
            f"Schedule: `{cron_expr}` ({timezone})\n"
            f"Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}\n"
            f"Results will be delivered to this session."
        )
    except Exception as e:
        return f"Error creating cron job: {e}"


async def list_cron_jobs(**kwargs) -> str:
    """List all cron jobs for the calling agent."""
    agent_ctx = kwargs.get("_agent_context", {})
    agent_id = agent_ctx.get("agent_id")

    try:
        result = await _api_get("/api/cron/")
        jobs = result.get("cron_jobs", [])
        if agent_id:
            jobs = [j for j in jobs if j.get("agent_id") == agent_id]
        if not jobs:
            return "No cron jobs found."

        lines = []
        for j in jobs:
            status = "enabled" if j.get("enabled") else "disabled"
            last = j.get("last_status") or "never run"
            lines.append(
                f"- **{j['name']}** (id: `{j['id']}`)\n"
                f"  Schedule: `{j['cron_expr']}` | Status: {status} | Last: {last}\n"
                f"  Prompt: {j['prompt'][:80]}{'...' if len(j['prompt']) > 80 else ''}"
            )
        return f"Found {len(jobs)} cron job(s):\n\n" + "\n".join(lines)
    except Exception as e:
        return f"Error listing cron jobs: {e}"


async def delete_cron_job(cron_id: str, **kwargs) -> str:
    """Delete a cron job by ID."""
    try:
        async with httpx.AsyncClient(timeout=15, headers=_INTERNAL_HEADERS) as client:
            res = await client.delete(f"{API_BASE}/api/cron/{cron_id}")
            if res.status_code == 200:
                return f"Cron job deleted (id: {cron_id})."
            return f"Failed to delete cron job: {res.text[:200]}"
    except Exception as e:
        return f"Error deleting cron job: {e}"


async def analyze_camera(camera_id: str, mode: str = "snapshot", duration: int = 5, **kwargs) -> str:
    camera_id = await _resolve_camera_id(camera_id)
    """Capture frame(s) from a camera's MJPEG stream and analyze with vision AI.

    Uses pure-Python MJPEG parsing (no ffmpeg dependency). In 'clip' mode,
    captures one frame per second over ``duration`` seconds.

    The ``_agent_context`` kwarg is injected by the chat route so we
    can use the calling agent's own LLM credentials for the vision call.
    """
    import time as _time

    agent_ctx = kwargs.get("_agent_context", {})

    # 1. Resolve stream URL
    try:
        cam = await _api_get(f"/api/cameras/{camera_id}")
        if cam.get("status") != "running":
            return f"Camera '{cam.get('name', camera_id)}' is not running (status: {cam.get('status')})"

        svc_name = cam.get("service_name")
        if not svc_name:
            return "Camera has no service — cannot capture."
        stream_url = f"http://{svc_name}.{settings.k8s_namespace}.svc.cluster.local:8081/"
    except Exception as e:
        return f"Error resolving camera stream: {e}"

    cam_name = cam.get("name", camera_id)

    # 2. Capture frames from MJPEG stream (no ffmpeg needed)
    try:
        if mode == "clip":
            duration = max(3, min(10, duration))
            frames = await _capture_mjpeg_frames(stream_url, count=duration, interval=1.0)
        else:
            frames = await _capture_mjpeg_frames(stream_url, count=1, interval=0)

        if not frames:
            return "Could not capture any frames from the camera stream."
    except httpx.TimeoutException:
        return f"Camera stream timed out. Ensure camera '{cam_name}' is running."
    except Exception as e:
        return f"Error capturing frames: {e}"

    # 3. Encode to base64
    b64_images = [base64.b64encode(f).decode() for f in frames]

    # 4. Send to vision LLM
    provider = agent_ctx.get("provider", "openai")
    model = agent_ctx.get("model", "gpt-4o")
    api_key = (
        agent_ctx.get("api_key")
        or os.getenv("ANTHROPIC_API_KEY", "")
        or os.getenv("OPENAI_API_KEY", "")
    )
    vision_prompt = (
        f"These are {len(b64_images)} frame(s) captured over {duration} seconds "
        f"from security camera '{cam_name}'. "
        "Describe what you see in detail. Note any people, their actions, "
        "objects, environment, activity, or anything unusual. "
        "If multiple frames are provided, note any changes between them."
    )

    try:
        if provider == "anthropic":
            description = await _vision_anthropic(api_key, model, b64_images, vision_prompt)
        else:
            base_url = (
                "https://api.openai.com/v1" if provider == "openai"
                else "http://ollama:11434/v1"
            )
            description = await _vision_openai(api_key, model, base_url, b64_images, vision_prompt)
    except Exception as e:
        return f"Vision API call failed: {e}"

    return f"[Camera: {cam_name} | Frames: {len(b64_images)} | Duration: {duration}s]\n{description}"


async def _capture_mjpeg_frames(stream_url: str, count: int = 1,
                                interval: float = 1.0) -> list[bytes]:
    """Extract JPEG frames from an MJPEG stream without ffmpeg.

    Reads the stream, extracts ``count`` frames spaced ``interval`` seconds apart.
    Returns a list of raw JPEG byte buffers.
    """
    import time as _time

    frames: list[bytes] = []
    timeout = max(15, count * interval + 10)
    last_capture = 0.0

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("GET", stream_url) as resp:
            buf = b""
            async for chunk in resp.aiter_bytes(chunk_size=16384):
                buf += chunk
                while True:
                    start = buf.find(b"\xff\xd8")
                    if start == -1:
                        buf = buf[-2:] if len(buf) > 2 else buf
                        break
                    end = buf.find(b"\xff\xd9", start + 2)
                    if end == -1:
                        break
                    frame = buf[start : end + 2]
                    buf = buf[end + 2 :]

                    now = _time.monotonic()
                    if now - last_capture >= interval or not frames:
                        frames.append(frame)
                        last_capture = now
                        if len(frames) >= count:
                            return frames
    return frames


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


async def file_write(path: str, content: str, **kwargs) -> str:
    """Write text content to a file in the shared agent filesystem."""
    try:
        result = await _api_post("/api/files/write", {"path": path, "content": content})
        return f"File written: {path} ({result.get('size', '?')} bytes)"
    except Exception as e:
        return f"Error writing file: {e}"


async def file_read(path: str, **kwargs) -> str:
    """Read a text file from the shared agent filesystem."""
    try:
        result = await _api_get(f"/api/files/read/{path}")
        if "content" in result:
            return f"File: {path} ({result.get('size', '?')} bytes)\n---\n{result['content']}"
        return f"File {path} is binary ({result.get('mime_type', 'unknown type')}), cannot display as text."
    except Exception as e:
        return f"Error reading file: {e}"


async def file_list(prefix: str = "", **kwargs) -> str:
    """List files and directories in the shared agent filesystem."""
    try:
        result = await _api_get(f"/api/files/?prefix={prefix}")
        files = result.get("files", [])
        if not files:
            return f"No files found in '{prefix or '/'}'."
        lines = []
        for f in files:
            if f["is_dir"]:
                lines.append(f"  [DIR]  {f['name']}/")
            else:
                size = f.get("size", 0)
                unit = "B"
                if size > 1024 * 1024:
                    size = size / (1024 * 1024)
                    unit = "MB"
                elif size > 1024:
                    size = size / 1024
                    unit = "KB"
                lines.append(f"  {f['name']}  ({size:.1f} {unit})")
        return f"Files in '{prefix or '/'}':\n" + "\n".join(lines)
    except Exception as e:
        return f"Error listing files: {e}"


PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".3gp"}

async def send_media(path: str, caption: str = "", media_type: str = "auto", **kwargs) -> str:
    """Queue a file or URL for delivery to the user's chat.
    Accepts: filesystem paths (e.g. 'snapshots/file.jpg'), API paths (e.g. '/api/recordings/{id}/download'),
    or full URLs (e.g. 'https://...')."""
    try:
        # Determine if this is an API path, full URL, or filesystem path
        is_api_path = path.startswith("/api/")
        is_full_url = path.startswith("http://") or path.startswith("https://")
        is_fs_path = not is_api_path and not is_full_url

        info = {}
        if is_fs_path:
            info = await _api_get(f"/api/files/info/{path}")
            if info.get("is_dir"):
                return f"Error: '{path}' is a directory, not a file."

        if media_type == "auto":
            ext = os.path.splitext(path)[1].lower()
            if ext in PHOTO_EXTENSIONS:
                media_type = "photo"
            elif ext in VIDEO_EXTENSIONS:
                media_type = "video"
            elif "/api/recordings/" in path and "/download" in path:
                # Recording download URLs have no extension but are always video
                media_type = "video"
            else:
                media_type = "document"

        if is_full_url:
            url = path
        elif is_api_path:
            url = path
        else:
            encoded = "/".join(quote(seg, safe="") for seg in path.split("/"))
            url = f"/api/files/read/{encoded}"

        media_entry = {
            "path": path,
            "url": url,
            "caption": caption,
            "media_type": media_type,
            "size": info.get("size"),
            "mime_type": info.get("mime_type"),
        }

        ctx = kwargs.get("_agent_context", {})
        if "pending_media" in ctx:
            ctx["pending_media"].append(media_entry)

        return f"Media queued for delivery: {path} ({media_type}, {info.get('size', '?')} bytes)"
    except Exception as e:
        if "404" in str(e) or "not found" in str(e).lower():
            return f"File not found: '{path}'. Use list_files to see available files, or write_file to create one first."
        return f"Error preparing media: {e}"


def _media_type_from_item(item: dict) -> str:
    """Map a structured media item to send_media's media_type."""
    try:
        raw_type = (item.get("type") or "").lower().lstrip(".")
        path = (item.get("path") or "").lower()
        ext = raw_type or os.path.splitext(path)[1].lower().lstrip(".")
        dot_ext = f".{ext}" if ext else ""
        if dot_ext in PHOTO_EXTENSIONS:
            return "photo"
        if dot_ext in VIDEO_EXTENSIONS:
            return "video"
        # Recording download URLs have no extension
        if "/api/recordings/" in path and "/download" in path:
            return "video"
    except Exception:
        pass
    return "document"


async def deliver_media_message(
    media: list,
    general_caption: str | None = None,
    session_id: str | None = None,
    **kwargs,
) -> str:
    """Persist a structured assistant_media message and queue attachments for delivery."""
    ctx = kwargs.get("_agent_context", {}) or {}
    agent_id = ctx.get("agent_id")
    resolved_session = session_id or ctx.get("session_id")
    if not agent_id or not resolved_session:
        return "Error: agent context missing agent_id/session_id"

    payload = {
        "general_caption": general_caption,
        "media": media or [],
    }

    # 1) Persist as an assistant_media message in chat history
    try:
        await _api_post(f"/api/chat/{agent_id}/messages/save", {
            "session_id": resolved_session,
            "role": "assistant_media",
            "content": payload,
            "source": "agent",
            "source_user": ctx.get("source_user"),
        })
    except Exception as e:
        return f"Error: failed to persist media message ({e})"

    # 2) Queue each item for channel delivery (Telegram, etc.)
    #    Mark as _already_persisted so callers don't save them again.
    queued = 0
    pending = ctx.get("pending_media")
    for item in (media or []):
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if not path or not isinstance(path, str):
            continue
        caption = item.get("caption") or general_caption or ""
        media_type = _media_type_from_item(item)
        is_api_path = path.startswith("/api/")
        is_full_url = path.startswith("http://") or path.startswith("https://")
        if is_full_url:
            url = path
        elif is_api_path:
            url = path
        else:
            encoded = "/".join(quote(seg, safe="") for seg in path.split("/"))
            url = f"/api/files/read/{encoded}"
        if pending is not None:
            pending.append({
                "path": path,
                "url": url,
                "caption": caption,
                "media_type": media_type,
                "_already_persisted": True,
            })
            queued += 1

    return f"Delivered {len(media or [])} media item(s) to session {resolved_session}. Queued {queued} attachment(s)."


async def file_delete(path: str, **kwargs) -> str:
    """Delete a file from the shared agent filesystem."""
    try:
        async with httpx.AsyncClient(timeout=30, headers=_INTERNAL_HEADERS) as client:
            res = await client.delete(f"{API_BASE}/api/files/{path}")
            result = res.json()
        return result.get("message", f"Deleted: {path}")
    except Exception as e:
        return f"Error deleting file: {e}"


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
    "app.tools.handlers.get_recording": get_recording,
    "app.tools.handlers.list_nodes": list_nodes,
    "app.tools.handlers.scan_cameras": scan_cameras,
    "app.tools.handlers.system_info": system_info,
    "app.tools.handlers.send_alert": send_alert,
    "app.tools.handlers.web_search": web_search,
    "app.tools.handlers.custom_api_call": custom_api_call,
    "app.tools.handlers.spawn_agent": spawn_agent,
    "app.tools.handlers.delegate_task": delegate_task,
    "app.tools.handlers.clone_agent": clone_agent,
    "app.tools.handlers.analyze_camera": analyze_camera,
    "app.tools.handlers.create_cron_job": create_cron_job,
    "app.tools.handlers.list_cron_jobs": list_cron_jobs,
    "app.tools.handlers.delete_cron_job": delete_cron_job,
    "app.tools.handlers.file_write": file_write,
    "app.tools.handlers.file_read": file_read,
    "app.tools.handlers.file_list": file_list,
    "app.tools.handlers.file_delete": file_delete,
    "app.tools.handlers.send_media": send_media,
    "app.tools.handlers.deliver_media_message": deliver_media_message,
}


async def execute_tool(
    tool_name: str,
    arguments: dict,
    agent_context: dict | None = None,
) -> tuple[str, list[dict]]:
    """Execute a tool by its function name.

    Returns (result_text, media_items).  ``media_items`` is populated when a
    tool like ``send_media`` queues files for delivery.
    """
    from app.tools.registry import TOOLS_REGISTRY

    if agent_context is None:
        agent_context = {}
    media_list: list[dict] = []
    agent_context["pending_media"] = media_list
    arguments = {**arguments, "_agent_context": agent_context}

    for tool_id, tool in TOOLS_REGISTRY.items():
        if tool["name"] == tool_name:
            handler_path = tool["handler"]
            handler = HANDLER_MAP.get(handler_path)
            if handler:
                result = await handler(**arguments)
                return result, media_list
            return f"Handler not found: {handler_path}", []
    return f"Unknown tool: {tool_name}", []
