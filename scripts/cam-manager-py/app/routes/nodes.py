"""
Node management routes
"""
import asyncio
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.services.k8s import K8sService
from app.config import get_settings

router = APIRouter(prefix="/api/nodes", tags=["nodes"])
settings = get_settings()


class USBCamera(BaseModel):
    device_path: str
    device_name: str
    node_name: str
    node_ip: str


class ScanResult(BaseModel):
    cameras: list[USBCamera]
    total: int
    scanned_nodes: list[str]
    errors: list[str]


@router.get("/")
@router.get("")
async def list_nodes():
    """Get all cluster nodes"""
    k8s = K8sService()
    nodes = await k8s.get_nodes()
    return nodes


@router.get("/{name}")
async def get_node(name: str):
    """Get a specific node"""
    k8s = K8sService()
    nodes = await k8s.get_nodes()
    for node in nodes:
        if node["name"] == name:
            return node
    return {"error": "Node not found"}, 404


async def _scan_node_cameras(node_name: str, node_ip: str) -> tuple[list[USBCamera], Optional[str]]:
    """Scan a node for USB cameras via SSH using paramiko"""
    import paramiko
    cameras = []
    error = None
    
    # Determine username based on node
    username = "ace" if node_name in ["ace", "falcon"] else "root"
    password = "amazingct"
    
    try:
        # Run SSH in thread pool to avoid blocking
        def ssh_scan():
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(node_ip, username=username, password=password, timeout=5)
            
            cmd = 'for d in /dev/video*; do [ -e "$d" ] && echo "$d|$(cat /sys/class/video4linux/$(basename $d)/name 2>/dev/null || echo Unknown)"; done'
            stdin, stdout, stderr = client.exec_command(cmd, timeout=10)
            output = stdout.read().decode().strip()
            err = stderr.read().decode().strip()
            client.close()
            return output, err
        
        loop = asyncio.get_event_loop()
        output, err = await asyncio.wait_for(
            loop.run_in_executor(None, ssh_scan),
            timeout=15
        )
        
        if output:
            for line in output.split('\n'):
                if '|' in line:
                    device_path, device_name = line.split('|', 1)
                    if device_path and device_name:
                        cameras.append(USBCamera(
                            device_path=device_path.strip(),
                            device_name=device_name.strip(),
                            node_name=node_name,
                            node_ip=node_ip,
                        ))
        elif err and not output:
            error = err[:100]
            
    except asyncio.TimeoutError:
        error = f"Timeout connecting to {node_name}"
    except Exception as e:
        error = f"{node_name}: {str(e)[:80]}"
    
    return cameras, error


@router.get("/scan/cameras", response_model=ScanResult)
async def scan_usb_cameras(node: Optional[str] = None):
    """Scan nodes for available USB cameras"""
    k8s = K8sService()
    nodes = await k8s.get_nodes()
    
    # Filter nodes if specified
    if node:
        nodes = [n for n in nodes if n["name"] == node]
        if not nodes:
            raise HTTPException(status_code=404, detail=f"Node {node} not found")
    
    all_cameras = []
    scanned_nodes = []
    errors = []
    
    # Scan each node concurrently
    tasks = []
    for n in nodes:
        if n["ready"] and n["ip"]:
            tasks.append(_scan_node_cameras(n["name"], n["ip"]))
            scanned_nodes.append(n["name"])
    
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, tuple):
                cameras, error = result
                all_cameras.extend(cameras)
                if error:
                    errors.append(error)
            elif isinstance(result, Exception):
                errors.append(str(result)[:100])
    
    return ScanResult(
        cameras=all_cameras,
        total=len(all_cameras),
        scanned_nodes=scanned_nodes,
        errors=errors,
    )
