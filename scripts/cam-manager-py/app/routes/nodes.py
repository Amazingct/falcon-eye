"""
Node management routes
"""
from fastapi import APIRouter
from app.services.k8s import K8sService

router = APIRouter(prefix="/api/nodes", tags=["nodes"])


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
