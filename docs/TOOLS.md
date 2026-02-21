# Tools Reference

Falcon-Eye agents use tools to interact with cameras, the cluster, the filesystem, other agents, and external services. Tools are executed centrally on the API server — agent pods call back to the API via `POST /api/tools/execute`.

Each tool has a **Tool ID** (used in agent configuration) and a **Function Name** (used in LLM tool calls).

---

## Cameras

| Tool ID | Function Name | Description |
|---------|--------------|-------------|
| `camera_list` | `list_cameras` | Get all cameras and their current status |
| `camera_status` | `camera_status` | Check if a specific camera is online |
| `camera_control` | `control_camera` | Start, stop, or restart a camera |
| `camera_snapshot` | `camera_snapshot` | Grab a snapshot frame from a running camera and save it to the filesystem |
| `camera_analyze` | `analyze_camera` | Capture a frame or short clip and analyze it with vision AI |

### `list_cameras`

Returns a markdown-formatted list of all cameras with their name, UUID, status, protocol, and node.

**Parameters:** None

**Example output:**
```
Found 3 cameras:
- **Office Camera** (id: `550e8400-...`) — running | usb on k3s-1
- **Front Door** (id: `660f9511-...`) — running | rtsp on k3s-2
- **Backyard** (id: `771a0622-...`) — stopped | rtsp on k3s-1
```

---

### `camera_status`

Check a single camera's status, protocol, and node.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `camera_id` | string | yes | Camera UUID |

---

### `control_camera`

Start, stop, or restart a camera's streaming pod.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `camera_id` | string | yes | Camera UUID |
| `action` | string | yes | `start`, `stop`, or `restart` |

---

### `camera_snapshot`

Captures a single JPEG frame from a running camera's MJPEG stream and uploads it to the shared filesystem.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `camera_id` | string | yes | Camera UUID |

**Returns:** Path to the saved snapshot file (e.g., `snapshots/office-camera-20260220-103000.jpg`).

**Typical workflow:** Call `camera_snapshot` to capture, then `send_media` to deliver the image to the user.

---

### `analyze_camera`

Captures a frame (or short clip) from a camera and sends it to a vision LLM for analysis. Returns an AI-generated description of what the camera sees.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `camera_id` | string | yes | Camera UUID |
| `mode` | string | no | `snapshot` (default) or `clip` |
| `duration` | integer | no | Clip duration in seconds, 3–5 (default: 3, only for clip mode) |

---

## Recording

| Tool ID | Function Name | Description |
|---------|--------------|-------------|
| `recording_start` | `start_recording` | Start recording on a camera |
| `recording_stop` | `stop_recording` | Stop an active recording |
| `recording_list` | `list_recordings` | List all recordings, optionally filtered by camera |

### `start_recording`

Starts recording on a camera. Auto-deploys the recorder pod if needed.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `camera_id` | string | yes | Camera UUID |

---

### `stop_recording`

Stops the active recording on a camera.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `camera_id` | string | yes | Camera UUID |

---

### `list_recordings`

Lists all recordings with their status, duration, and file size.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `camera_id` | string | no | Filter by camera UUID |

---

## System

| Tool ID | Function Name | Description |
|---------|--------------|-------------|
| `node_list` | `list_nodes` | Get cluster nodes and their health status |
| `node_scan` | `scan_cameras` | Scan cluster nodes for USB and network cameras |
| `system_info` | `system_info` | Get cluster resource usage and pod status |

### `list_nodes`

Returns cluster nodes with ready status, IP addresses, and architecture.

**Parameters:** None

---

### `scan_cameras`

Scans cluster nodes for USB devices and optionally probes the network for IP cameras.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `network` | boolean | no | Include network scan (default: true) |

---

### `system_info`

Returns cluster resource usage summary and pod status.

**Parameters:** None

---

## Agents

| Tool ID | Function Name | Description |
|---------|--------------|-------------|
| `agent_spawn` | `spawn_agent` | Create and start a new agent (Job for tasks, Deployment for persistent) |
| `agent_delegate` | `delegate_task` | Send a task to an already-running agent (async) |
| `agent_create_from` | `clone_agent` | Clone an existing agent's configuration |

### `spawn_agent`

Creates a new agent that inherits the calling agent's LLM config. Behavior depends on whether a `task` is provided:

**With `task` (ephemeral — K8s Job):**
- The agent runs as a **K8s Job** (run-to-completion, no restart)
- The tool **returns immediately** so the caller can continue working
- The spawned agent executes the task, posts the result back via the `/task-complete` callback
- The callback re-triggers the caller agent with the result and pushes to Telegram if configured
- The ephemeral agent DB record is **automatically deleted** on completion
- The K8s Job is auto-cleaned via `ttlSecondsAfterFinished`
- Ephemeral agents do NOT receive `spawn_agent`, `delegate_task`, or scheduling tools (prevents recursive loops)

**Without `task` (persistent — K8s Deployment):**
- The agent is created as a long-running Deployment with an HTTP server
- It stays running until explicitly stopped

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | yes | Agent display name |
| `system_prompt` | string | no | System prompt (defaults to generic) |
| `tools` | string[] | no | Tool IDs to enable (inherits parent's if omitted; meta-tools filtered for tasks) |
| `channel_type` | string | no | `telegram`, `webhook`, or `custom` (inherits parent's) |
| `task` | string | no | Task to execute as a background Job |

**Example:**
```
Agent: I'll spawn a researcher to look into that for you.
[calls spawn_agent(name="researcher", task="Find best practices for outdoor IP camera placement")]
Tool returns: "Agent 'researcher' has been spawned and is executing the task as a background Job..."
Agent: I've dispatched a researcher agent to look into outdoor camera placement. I'll share the findings once it reports back.
... (later, callback arrives with research results) ...
Agent: The researcher found that outdoor cameras should be mounted 8-10 feet high...
```

---

### `delegate_task`

Sends a task to an **already-running** agent asynchronously. Returns immediately — the result is delivered as a system message once the target agent finishes.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `agent_id` | string | yes | UUID of the target agent (must be running) |
| `task` | string | yes | The task or question to send |

---

### `clone_agent`

Creates a new agent by copying an existing agent's full configuration (provider, model, tools, system prompt, etc.). Does not start the new agent automatically.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `source_agent_id` | string | yes | UUID of the agent to clone |
| `new_name` | string | yes | Name for the new agent |
| `override_system_prompt` | string | no | Replace the cloned system prompt |
| `override_tools` | string[] | no | Replace the cloned tool list |

---

## Filesystem

| Tool ID | Function Name | Description |
|---------|--------------|-------------|
| `file_read` | `read_file` | Read a text file from the shared filesystem |
| `file_write` | `write_file` | Write text content to a file |
| `file_list` | `list_files` | List files and directories |
| `file_delete` | `delete_file` | Delete a file |

All filesystem tools operate on the shared agent filesystem (`/agent-files` PVC), which is mounted on the API pod and all agent pods. Paths are relative to the shared root.

### `read_file`

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `path` | string | yes | File path (e.g., `notes/report.txt`) |

---

### `write_file`

Creates parent directories automatically.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `path` | string | yes | File path (e.g., `notes/report.txt`) |
| `content` | string | yes | Text content to write |

---

### `list_files`

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `prefix` | string | no | Directory to list (empty for root) |

---

### `delete_file`

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `path` | string | yes | File path to delete |

---

## Messaging

| Tool ID | Function Name | Description |
|---------|--------------|-------------|
| `send_media` | `send_media` | Send an image, video, or document to the user's chat |

### `send_media`

Sends a file from the shared filesystem to the user's chat (Dashboard or Telegram). The file must already exist — use `camera_snapshot`, `write_file`, or `list_files` first.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `path` | string | yes | File path in the shared filesystem |
| `caption` | string | no | Caption to display with the media |
| `media_type` | string | no | `auto` (default), `photo`, `video`, or `document` |

---

## Alerts

| Tool ID | Function Name | Description |
|---------|--------------|-------------|
| `alert_send` | `send_alert` | Log an alert and push to Telegram agents |

### `send_alert`

Appends the alert to `alerts/alerts.log` on the shared filesystem and pushes it to any running Telegram agents that have a configured `chat_id`.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `message` | string | yes | Alert message |
| `severity` | string | no | `info` (default), `warning`, or `critical` |

---

## Scheduling

| Tool ID | Function Name | Description |
|---------|--------------|-------------|
| `cron_create` | `create_cron_job` | Create a recurring scheduled job in the agent's current session |
| `cron_list` | `list_cron_jobs` | List the agent's scheduled cron jobs |
| `cron_delete` | `delete_cron_job` | Delete a cron job |

### `create_cron_job`

Creates a K8s CronJob that sends a prompt to the agent on a recurring schedule. The cron results are delivered to the **caller's current chat session**, keeping the conversation continuous. The agent can set up monitoring, reports, or any recurring task.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | yes | Display name (e.g., "Morning camera check") |
| `cron_expr` | string | yes | Standard cron expression |
| `prompt` | string | yes | The prompt to execute each time the cron fires |
| `timezone` | string | no | Timezone (default: `UTC`) |
| `timeout_seconds` | integer | no | Max execution time (default: 120) |

**Common cron expressions:**

| Expression | Meaning |
|-----------|---------|
| `*/30 * * * *` | Every 30 minutes |
| `0 * * * *` | Every hour |
| `0 9 * * *` | Daily at 9:00 AM |
| `0 9 * * 1-5` | Weekdays at 9:00 AM |
| `0 */6 * * *` | Every 6 hours |
| `0 0 * * 0` | Weekly on Sunday at midnight |

**Example:**
```
User: Check all my cameras every morning at 8 AM and send me a report.
Agent: [calls create_cron_job(
    name="Morning camera report",
    cron_expr="0 8 * * *",
    prompt="Check the status of all cameras, take a snapshot of each running camera, and send me a summary report."
)]
Tool returns: Cron job 'Morning camera report' created.
Agent: Done! I've set up a daily camera report at 8:00 AM UTC. Every morning I'll check all cameras, take snapshots, and send you a summary right here in this conversation.
```

When the cron fires, the cron-runner sends the prompt to the agent via the chat API using the saved session ID. The agent processes it with full tool access (snapshots, analysis, etc.), and the response appears in the same session. If the agent has Telegram configured, the response is also pushed there.

---

### `list_cron_jobs`

Lists all cron jobs belonging to the calling agent.

**Parameters:** None

---

### `delete_cron_job`

Deletes a cron job and its K8s CronJob resource.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `cron_id` | string | yes | UUID of the cron job to delete |

---

## External

| Tool ID | Function Name | Description |
|---------|--------------|-------------|
| `web_search` | `web_search` | Search the web via DuckDuckGo |
| `custom_api` | `custom_api_call` | Call a user-defined HTTP endpoint |

### `web_search`

Searches DuckDuckGo and returns the top 5 results (title, snippet, URL). Falls back to the DuckDuckGo instant answer API if HTML parsing yields no results.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `query` | string | yes | Search query |

---

### `custom_api_call`

Makes an HTTP request to any URL. Useful for integrating with external services.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `url` | string | yes | URL to call |
| `method` | string | no | `GET` (default), `POST`, `PUT`, or `DELETE` |
| `body` | string | no | Request body (JSON string) |

---

## Quick Reference

All 25 tools at a glance:

| Tool ID | Function | Category |
|---------|----------|----------|
| `camera_list` | `list_cameras` | cameras |
| `camera_status` | `camera_status` | cameras |
| `camera_control` | `control_camera` | cameras |
| `camera_snapshot` | `camera_snapshot` | cameras |
| `camera_analyze` | `analyze_camera` | cameras |
| `recording_start` | `start_recording` | recording |
| `recording_stop` | `stop_recording` | recording |
| `recording_list` | `list_recordings` | recording |
| `node_list` | `list_nodes` | system |
| `node_scan` | `scan_cameras` | system |
| `system_info` | `system_info` | system |
| `agent_spawn` | `spawn_agent` | agents |
| `agent_delegate` | `delegate_task` | agents |
| `agent_create_from` | `clone_agent` | agents |
| `cron_create` | `create_cron_job` | scheduling |
| `cron_list` | `list_cron_jobs` | scheduling |
| `cron_delete` | `delete_cron_job` | scheduling |
| `file_read` | `read_file` | filesystem |
| `file_write` | `write_file` | filesystem |
| `file_list` | `list_files` | filesystem |
| `file_delete` | `delete_file` | filesystem |
| `send_media` | `send_media` | messaging |
| `alert_send` | `send_alert` | alerts |
| `web_search` | `web_search` | external |
| `custom_api` | `custom_api_call` | external |

## Assigning Tools to Agents

Tools are assigned per-agent via the dashboard (Agents page) or the API:

```bash
# Set tools for an agent
curl -X PUT http://localhost:8000/api/agents/{agent_id}/tools \
  -H 'Content-Type: application/json' \
  -d '{"tools": ["camera_list", "camera_snapshot", "send_media", "agent_spawn"]}'
```

Agents can only use the tools explicitly assigned to them. The LLM sees tool descriptions and schemas in its system prompt and decides when to call them.
