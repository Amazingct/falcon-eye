"""
Falcon-Eye Chatbot Tools (Read-Only)
Default tools for checking cluster and camera status
"""
from typing import Optional
from langchain_core.tools import tool
import httpx


# Base URL for internal API calls
API_BASE = "http://localhost:3000"
DEFAULT_TIMEOUT = 30  # Increased timeout for reliability


@tool
def get_cameras() -> str:
    """Get list of all cameras with their current status.
    Returns camera names, protocols, status (running/stopped/error), and node locations.
    """
    try:
        response = httpx.get(f"{API_BASE}/api/cameras/", timeout=DEFAULT_TIMEOUT)
        if response.status_code != 200:
            return f"Error fetching cameras: {response.status_code}"
        
        data = response.json()
        cameras = data.get("cameras", [])
        
        if not cameras:
            return "No cameras configured in the system."
        
        result = f"Found {len(cameras)} camera(s):\n\n"
        for cam in cameras:
            status_emoji = "🟢" if cam["status"] == "running" else "🔴" if cam["status"] == "error" else "⚪"
            result += f"{status_emoji} **{cam['name']}**\n"
            result += f"   - Protocol: {cam['protocol'].upper()}\n"
            result += f"   - Status: {cam['status']}\n"
            result += f"   - Node: {cam.get('node_name', 'N/A')}\n"
            if cam.get('stream_url'):
                result += f"   - Stream: {cam['stream_url']}\n"
            result += "\n"
        
        return result
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def get_camera_details(camera_name: str) -> str:
    """Get detailed information about a specific camera by name.
    
    Args:
        camera_name: The name of the camera to look up
    """
    try:
        response = httpx.get(f"{API_BASE}/api/cameras/", timeout=DEFAULT_TIMEOUT)
        if response.status_code != 200:
            return f"Error fetching cameras: {response.status_code}"
        
        data = response.json()
        cameras = data.get("cameras", [])
        
        # Find camera by name (case-insensitive)
        camera = None
        for cam in cameras:
            if cam["name"].lower() == camera_name.lower():
                camera = cam
                break
        
        if not camera:
            available = ", ".join([c["name"] for c in cameras]) or "None"
            return f"Camera '{camera_name}' not found. Available cameras: {available}"
        
        status_emoji = "🟢" if camera["status"] == "running" else "🔴" if camera["status"] == "error" else "⚪"
        
        result = f"{status_emoji} **{camera['name']}**\n\n"
        result += f"**Protocol:** {camera['protocol'].upper()}\n"
        result += f"**Status:** {camera['status']}\n"
        result += f"**Node:** {camera.get('node_name', 'N/A')}\n"
        result += f"**Resolution:** {camera.get('resolution', 'N/A')}\n"
        result += f"**Framerate:** {camera.get('framerate', 'N/A')} FPS\n"
        result += f"**Location:** {camera.get('location') or 'Not set'}\n"
        
        if camera.get('stream_url'):
            result += f"**Stream URL:** {camera['stream_url']}\n"
        if camera.get('control_url'):
            result += f"**Control URL:** {camera['control_url']}\n"
        if camera.get('source_url'):
            result += f"**Source:** {camera['source_url']}\n"
        if camera.get('device_path'):
            result += f"**Device:** {camera['device_path']}\n"
        
        if camera.get('metadata', {}).get('error'):
            result += f"\n⚠️ **Error:** {camera['metadata']['error']}\n"
        
        return result
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def get_cluster_nodes() -> str:
    """Get list of all Kubernetes cluster nodes with their status.
    Shows node names, IPs, ready status, and architecture.
    """
    try:
        response = httpx.get(f"{API_BASE}/api/nodes/", timeout=DEFAULT_TIMEOUT)
        if response.status_code != 200:
            return f"Error fetching nodes: {response.status_code}"
        
        nodes = response.json()
        
        if not nodes:
            return "No nodes found in the cluster."
        
        result = f"Cluster has {len(nodes)} node(s):\n\n"
        for node in nodes:
            status_emoji = "🟢" if node.get("ready") else "🔴"
            result += f"{status_emoji} **{node['name']}**\n"
            result += f"   - IP: {node.get('ip', 'N/A')}\n"
            result += f"   - Ready: {'Yes' if node.get('ready') else 'No'}\n"
            result += f"   - Architecture: {node.get('architecture', 'N/A')}\n"
            
            if node.get('taints'):
                taints = [f"{t['key']}={t.get('value', '')}:{t['effect']}" for t in node['taints']]
                result += f"   - Taints: {', '.join(taints)}\n"
            result += "\n"
        
        return result
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def get_system_status() -> str:
    """Get overall Falcon-Eye system status.
    Shows API health, total cameras, running cameras, and cluster node count.
    """
    try:
        # Check API health
        health_response = httpx.get(f"{API_BASE}/health", timeout=DEFAULT_TIMEOUT)
        api_healthy = health_response.status_code == 200
        
        # Get cameras
        cameras_response = httpx.get(f"{API_BASE}/api/cameras/", timeout=DEFAULT_TIMEOUT)
        cameras = cameras_response.json().get("cameras", []) if cameras_response.status_code == 200 else []
        
        # Get nodes
        nodes_response = httpx.get(f"{API_BASE}/api/nodes/", timeout=DEFAULT_TIMEOUT)
        nodes = nodes_response.json() if nodes_response.status_code == 200 else []
        
        # Calculate stats
        total_cameras = len(cameras)
        running_cameras = len([c for c in cameras if c["status"] == "running"])
        error_cameras = len([c for c in cameras if c["status"] == "error"])
        total_nodes = len(nodes)
        ready_nodes = len([n for n in nodes if n.get("ready")])
        
        result = "## 🦅 Falcon-Eye System Status\n\n"
        result += f"**API:** {'🟢 Healthy' if api_healthy else '🔴 Unhealthy'}\n\n"
        
        result += "**Cameras:**\n"
        result += f"   - Total: {total_cameras}\n"
        result += f"   - Running: {running_cameras} 🟢\n"
        if error_cameras > 0:
            result += f"   - Errors: {error_cameras} 🔴\n"
        result += f"   - Stopped: {total_cameras - running_cameras - error_cameras} ⚪\n\n"
        
        result += "**Cluster:**\n"
        result += f"   - Nodes: {ready_nodes}/{total_nodes} ready\n"
        
        return result
    except Exception as e:
        return f"Error getting system status: {str(e)}"


@tool  
def get_settings() -> str:
    """Get current Falcon-Eye system settings.
    Shows default resolution, framerate, cleanup interval, and node IPs.
    """
    try:
        response = httpx.get(f"{API_BASE}/api/settings/", timeout=DEFAULT_TIMEOUT)
        if response.status_code != 200:
            return f"Error fetching settings: {response.status_code}"
        
        settings = response.json()
        
        result = "## ⚙️ System Settings\n\n"
        result += f"**Default Resolution:** {settings.get('default_resolution', 'N/A')}\n"
        result += f"**Default Framerate:** {settings.get('default_framerate', 'N/A')} FPS\n"
        result += f"**Cleanup Interval:** {settings.get('cleanup_interval', 'N/A')}\n"
        result += f"**Creating Timeout:** {settings.get('creating_timeout_minutes', 'N/A')} minutes\n"
        result += f"**Namespace:** {settings.get('k8s_namespace', 'N/A')}\n\n"
        
        node_ips = settings.get('node_ips', {})
        if node_ips:
            result += "**Node IPs:**\n"
            for name, ip in node_ips.items():
                result += f"   - {name}: {ip}\n"
        
        return result
    except Exception as e:
        return f"Error: {str(e)}"


# All available tools
AVAILABLE_TOOLS = {
    "get_cameras": get_cameras,
    "get_camera_details": get_camera_details,
    "get_cluster_nodes": get_cluster_nodes,
    "get_system_status": get_system_status,
    "get_settings": get_settings,
}

# Default enabled tools (read-only)
DEFAULT_TOOLS = [
    "get_cameras",
    "get_camera_details", 
    "get_cluster_nodes",
    "get_system_status",
    "get_settings",
]


def get_enabled_tools(enabled_tool_names: list[str] = None) -> list:
    """Get list of tool instances for enabled tools"""
    if enabled_tool_names is None:
        enabled_tool_names = DEFAULT_TOOLS
    
    tools = []
    for name in enabled_tool_names:
        if name in AVAILABLE_TOOLS:
            tools.append(AVAILABLE_TOOLS[name])
    
    return tools
