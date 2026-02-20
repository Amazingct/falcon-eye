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

---

## AI Chatbot

If an Anthropic API key has been configured, you'll see a blue chat button (💬) in the bottom-right corner.

1. Click the chat button to open the assistant
2. Type questions like:
   - "How many cameras are online?"
   - "Show me the cameras on node k3s-1"
   - "What's the status of the front door camera?"
3. The assistant can read camera data and help with troubleshooting

### Chat Features

- **Sessions**: Click the list icon to see previous conversations
- **New Chat**: Click + to start a fresh conversation
- **Dock/Undock**: Toggle between a side panel and floating window
- **Resize**: Drag the left edge of the docked panel to resize

### Enabling the Chatbot

If the chatbot shows "Set ANTHROPIC_API_KEY to enable chat":

1. Click the **Settings** (gear) icon in the header
2. Under **Chatbot Settings**, enter your Anthropic API key
3. Click **Save**
4. The page will reload — the chatbot should now be active

Get an API key at: [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys)

---

## Settings

Click the **Settings** (gear) icon to access:

### Camera Defaults
- **Resolution**: Default resolution for new cameras (640×480 recommended)
- **Framerate**: Default FPS for new cameras

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

1. Check that your browser isn't blocking mixed content (HTTP stream on HTTPS page)
2. Try opening the stream URL directly: click Edit to see the camera's node and port
3. Try a different browser
4. Click **Restart** on the camera

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
