# User Manual

This guide is for anyone using Falcon-Eye's web dashboard. You don't need to know anything about Kubernetes, Docker, or command lines.

## Accessing the Dashboard

After installation, you'll see a URL like:

```
📊 Dashboard: http://192.168.1.207:30900
```

Open that URL in any web browser (Chrome, Firefox, Safari, Edge). Bookmark it for easy access.

> **Tip**: If you don't know the URL, ask whoever installed Falcon-Eye, or check the terminal where the install command was run.

---

## The Dashboard

When you open the dashboard, you'll see:

- **Header bar**: Camera/Recordings page toggle, Scan button, Add Camera button, Settings
- **Stats bar**: Total cameras, online count, offline count, node count
- **Camera grid**: Cards showing each camera's live preview
- **Chat button**: AI assistant (bottom-right corner, if configured)

You can switch between **Grid view** (thumbnail cards) and **List view** (table) using the toggle buttons in the header.

---

## Adding a USB Camera

USB cameras are webcams or similar devices plugged directly into one of your servers.

### Step 1: Scan for Cameras

1. Click the green **Scan** button in the header
2. Wait a few seconds — Falcon-Eye will search all your servers for connected USB cameras
3. You'll see a list of discovered cameras with their device names and which server they're on

### Step 2: Select and Add

1. Check the box next to each camera you want to add
2. Click **Add (X)** at the bottom
3. The cameras will appear on the dashboard with a spinning "ADDING..." badge

### Step 3: Wait for Stream

- The camera card will show a spinning icon while starting up
- After 30–60 seconds, the status changes to **LIVE** and the video preview appears
- Click the preview to see a full-size view

> **If it stays on "ADDING..." for more than 3 minutes**, the system will automatically mark it as an error. Try deleting and re-adding the camera.

---

## Adding a Network Camera (RTSP / ONVIF)

Network cameras are IP cameras connected to your local network (Wi-Fi or Ethernet).

### Step 1: Create the Camera

1. Click the blue **Add Camera** button
2. Fill in:
   - **Camera Name**: A friendly name (e.g., "Front Door", "Backyard")
   - **Camera Type**: Select "RTSP Stream", "ONVIF Camera", or "HTTP/MJPEG"
   - **Target Node**: Select any server (for network cameras, any will work)
   - **Source**: The camera's stream URL (see below for common formats)
3. Click **Add Camera**

### Common URL Formats

| Camera Brand | URL Format |
|-------------|-----------|
| Generic RTSP | `rtsp://username:password@192.168.1.100:554/stream1` |
| Hikvision | `rtsp://admin:password@192.168.1.100:554/Streaming/Channels/101` |
| Tuya / Smart Life | `rtsp://username:password@192.168.1.100:554/stream1` |
| Dahua | `rtsp://admin:password@192.168.1.100:554/cam/realmonitor?channel=1&subtype=0` |
| ONVIF | `onvif://admin:password@192.168.1.100:80` |
| HTTP/MJPEG | `http://192.168.1.100/mjpg/video.mjpg` |

### Step 2: Configure and Start

Network cameras are created in a **Stopped** state. This gives you a chance to configure them.

1. Click the **Edit** (pencil icon) button on the camera card
2. Enter or update the **Stream URL** with your camera's credentials
3. Adjust resolution and framerate if needed
4. Click **Save Changes**
5. Click the **Start** (play icon) button

The camera will go through "ADDING..." and then show **LIVE** with the video feed.

### Step 3: Scan for Network Cameras (Alternative)

Instead of manually entering URLs, you can use the **Scan** button:

1. Click **Scan** — it automatically scans both USB devices and your network for cameras
2. Network cameras found on common ports (554, 8554, 80, 8080) will appear in the results
3. Select and add them
4. Edit each camera to add credentials, then start it

---

## Understanding Camera Statuses

| Status | What It Means | What To Do |
|--------|--------------|------------|
| 🟢 **LIVE** | Camera is streaming — everything works | Nothing — enjoy! |
| 🔵 **ADDING...** | Camera is starting up | Wait 30–60 seconds |
| ⬜ **STOPPED** | Camera is configured but not streaming | Click Start (play button) |
| 🔴 **ERROR** | Something went wrong | Check the error message, try Restart or delete and re-add |
| 🟡 **DELETING...** | Camera is being removed | Wait for it to finish |

---

## Managing Cameras

### Start / Stop

- Click the **Play** button (▶) to start a stopped camera
- Click the **Pause** button (⏸) to stop a running camera

Stopping a camera removes its streaming pod but keeps the camera configuration. You can start it again anytime.

### Restart

Click the **Restart** button (↻) to stop and start a camera. Useful if the stream freezes or shows errors.

### Edit

Click the **Edit** button (pencil) to change:
- Camera name
- Stream URL (for network cameras)
- Location description
- Resolution (320×240 up to 1920×1080)
- Framerate (1–60 fps)

If you change the stream URL, the camera will automatically redeploy.

### Delete

Click the **Trash** button (🗑) to permanently remove a camera. You'll be asked to confirm. For USB cameras, there's a brief cooldown (about 20 seconds) before you can re-add the same device.

### Full-Size Preview

Click on any live camera's video preview to open a full-size view.

---

## Recording

### Start a Recording

1. Find a camera that shows **LIVE** status
2. Click the **Record** button (⊙) — it's next to the other camera action buttons
3. The button turns into a red pulsing **Stop** button (■)

The system creates a recorder that captures the video to an MP4 file.

### Stop a Recording

Click the red pulsing **Stop** button (■) on the camera card. The recording is saved and appears on the Recordings page.

### Viewing Recordings

1. Click **Recordings** in the header bar (next to "Cameras")
2. Recordings are grouped by camera — click a camera name to expand
3. Each recording shows: filename, start time, duration, file size, and status
4. Click **Play** (▶) to watch the recording in the browser
5. Click **Download** (⬇) to save the MP4 file to your computer
6. Click **Trash** (🗑) to delete a recording

### Recording Statuses

| Status | Meaning |
|--------|---------|
| 🔴 Recording | Currently recording |
| 🟢 Completed | Finished successfully |
| ⬜ Stopped | Stopped by user or system |
| 🔴 Failed | Recording encountered an error |

> **Note**: If a camera is deleted while recording, the recording is preserved and marked with a "Camera Deleted" badge. You can still play and download it.

> **Note**: Recordings are stored on the cluster node where the recorder pod ran. The system automatically locates and retrieves recordings from any node when you play or download them.

---

## AI Agents

Falcon-Eye includes a full multi-agent AI system. Agents are LLM-powered assistants that can manage cameras, take snapshots, search the web, read/write files, and even spawn other agents to handle subtasks.

### Accessing Agents

There are two ways to interact with agents:

1. **Dashboard Chat**: Click the chat button in the bottom-right corner of the dashboard. This connects to your main agent.
2. **Agents Page**: Click "Agents" in the navigation bar to see all agents, create new ones, and manage their settings.

### What Agents Can Do

Agents have access to **tools** that let them take actions:

| Tool | What It Does |
|------|-------------|
| List Cameras | See all cameras and their status |
| Camera Snapshot | Take a photo from any camera |
| Analyze Camera | Use vision AI to describe what a camera sees |
| Start/Stop Camera | Control camera streaming |
| Start/Stop Recording | Control recording |
| Web Search | Search the internet for information |
| Read/Write Files | Access the shared filesystem |
| Send Media | Send photos or files to your chat |
| Send Alert | Log and push alerts to Telegram |
| Spawn Agent | Create a temporary agent for a subtask |
| Delegate Task | Send a task to another running agent |

### Talking to Your Agent

Type naturally — the agent understands plain English:

- "How many cameras are online?"
- "Take a snapshot of the office camera"
- "What does the front door camera see right now?"
- "Search the web for how to configure ONVIF cameras"
- "Start recording on all cameras"
- "Create a new agent called 'researcher' and have it find information about security camera best practices"

Responses are rendered as **markdown** with formatting, code blocks, and lists.

### Chat Features

- **Sessions**: Click the list icon to see previous conversations
- **New Chat**: Click + to start a fresh conversation
- **Dock/Undock**: Toggle between a side panel and floating window
- **Resize**: Drag the left edge of the docked panel to resize

### Managing Agents

On the **Agents** page:

1. **Create**: Click "Add Agent" to create a new agent with a custom name, system prompt, and tool set
2. **Configure**: Set the LLM provider (OpenAI or Anthropic), model, temperature, and which tools the agent can use
3. **Start/Stop**: Deploy or remove the agent's pod
4. **Telegram**: Configure a Telegram bot token and chat ID to connect an agent to Telegram
5. **Chat**: Click "Chat" on any agent to open a conversation

### Multi-Agent Collaboration

Agents can work together:

- **Spawn Agent**: An agent can create a temporary helper agent with a specific task. The helper runs in the background, and when it finishes, the result is automatically delivered back to the original agent's conversation.
- **Delegate Task**: An agent can send a task to another already-running agent and receive the result asynchronously.

This happens automatically when the agent decides it needs help — you don't need to manage it manually.

### Telegram Integration

To connect an agent to Telegram:

1. Create a Telegram bot via [@BotFather](https://t.me/BotFather)
2. On the Agents page, edit your agent
3. Set **Channel Type** to "telegram"
4. Enter the **Bot Token** and your **Chat ID**
5. Start the agent

The agent will now respond to messages in your Telegram chat with full tool access.

### Setting Up AI

To use agents, you need an API key from either:

- **Anthropic**: [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys)
- **OpenAI**: [platform.openai.com/api-keys](https://platform.openai.com/api-keys)

Configure the key in the agent's settings on the Agents page, or set it as an environment variable (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`).

---

## Settings

Click the **Settings** (gear) icon to access:

### Camera Defaults
- **Resolution**: Default resolution for new cameras (640×480 recommended)
- **Framerate**: Default FPS for new cameras

### Node Defaults
- **Default Camera Node**: Which node new cameras should be scheduled on (leave empty to let Kubernetes decide)
- **Default Recorder Node**: Which node new recorders should be scheduled on (leave empty to let Kubernetes decide)

### System Settings
- **Cleanup Interval**: How often the system checks for orphaned resources (default: every 2 minutes)
- **Creating Timeout**: How long to wait before marking a stuck camera as error (default: 3 minutes)

### Chatbot Settings
- Configure the Anthropic API key
- Enable/disable specific chatbot tools

### Actions
- **Save**: Save settings changes
- **Restart All**: Restart all components to apply settings (briefly interrupts streams)
- **Clear All Cameras**: ⚠️ Danger zone — deletes ALL cameras

---

## Multi-Node Setup

If your system has multiple servers (nodes), cameras are distributed across them:

- **USB cameras** automatically run on the server they're plugged into
- **Network cameras** can run on any server
- **Recordings** are stored on the node where the recorder runs, but can be played/downloaded from any node
- The node name appears on each camera card

You don't need to manage this — it happens automatically. The dashboard shows which node each camera is on.

---

## Troubleshooting

### Camera shows "ERROR"

1. Click the camera card to see the error message
2. Common causes:
   - USB device unplugged or in use by another program
   - Wrong RTSP URL or credentials
   - Camera is offline on the network
3. Fix the issue and click **Restart**

### Stream not loading (LIVE but no video)

1. Try a different browser (Chrome and Firefox work best)
2. Click **Restart** on the camera
3. Check Settings to make sure the system is working (check node counts)
4. Ask your system administrator to check if the pods are running

### Recording failed

1. Check the recording's error message on the Recordings page
2. Common causes:
   - Camera went offline during recording
   - Disk full on the server
   - Incompatible audio codec (should be handled automatically)
3. Delete the failed recording and try again

### Camera stuck on "ADDING..."

- Wait up to 3 minutes — the system will auto-timeout
- If it shows ERROR after timeout, try deleting and re-adding
- For USB cameras: make sure the device is plugged in and not in use

### Dashboard not loading

- Check that the URL is correct (default: `http://<server-ip>:30900`)
- Make sure you're on the same network as the server
- Ask your system administrator to check if the pods are running
