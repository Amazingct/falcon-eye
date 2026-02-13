"""Kubernetes deployment management service"""
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from typing import Optional
import logging

from app.config import get_settings
from app.models.camera import Camera
from app.services.converters import get_container_spec

logger = logging.getLogger(__name__)
settings = get_settings()


def load_k8s_config():
    """Load Kubernetes configuration"""
    if settings.k8s_config_path:
        config.load_kube_config(config_file=settings.k8s_config_path)
    elif settings.k8s_api_server and settings.k8s_token:
        configuration = client.Configuration()
        configuration.host = settings.k8s_api_server
        configuration.api_key = {"authorization": f"Bearer {settings.k8s_token}"}
        configuration.verify_ssl = False
        client.Configuration.set_default(configuration)
    else:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()


# Initialize K8s config
load_k8s_config()

apps_api = client.AppsV1Api()
core_api = client.CoreV1Api()


def generate_deployment(camera: Camera) -> tuple[dict, str]:
    """Generate K8s deployment manifest for a camera"""
    name_slug = camera.name.lower().replace(" ", "-").replace("_", "-")
    name_slug = "".join(c for c in name_slug if c.isalnum() or c == "-")
    deployment_name = f"cam-{name_slug}"
    
    container = get_container_spec(camera)
    
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": deployment_name,
            "namespace": settings.k8s_namespace,
            "labels": {
                "app": "falcon-eye",
                "component": "camera",
                "camera-id": str(camera.id),
                "protocol": camera.protocol,
            },
        },
        "spec": {
            "replicas": 1,
            "selector": {
                "matchLabels": {"camera-id": str(camera.id)},
            },
            "template": {
                "metadata": {
                    "labels": {
                        "app": "falcon-eye",
                        "component": "camera",
                        "camera-id": str(camera.id),
                        "protocol": camera.protocol,
                    },
                },
                "spec": {
                    "containers": [container],
                    "volumes": [],
                },
            },
        },
    }
    
    # Add USB device volume mount
    if camera.protocol == "usb":
        deployment["spec"]["template"]["spec"]["volumes"] = [{
            "name": "dev-video",
            "hostPath": {"path": camera.device_path or "/dev/video0"},
        }]
    
    # Add node selector and tolerations for specific nodes
    if camera.node_name:
        deployment["spec"]["template"]["spec"]["nodeSelector"] = {
            "kubernetes.io/hostname": camera.node_name,
        }
        
        if settings.is_jetson_node(camera.node_name):
            deployment["spec"]["template"]["spec"]["tolerations"] = [{
                "key": "dedicated",
                "operator": "Equal",
                "value": "jetson",
                "effect": "NoSchedule",
            }]
    
    return deployment, deployment_name


def generate_service(camera: Camera, deployment_name: str) -> tuple[dict, str]:
    """Generate K8s service manifest for a camera"""
    name_slug = camera.name.lower().replace(" ", "-").replace("_", "-")
    name_slug = "".join(c for c in name_slug if c.isalnum() or c == "-")
    service_name = f"svc-{name_slug}"
    
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": service_name,
            "namespace": settings.k8s_namespace,
            "labels": {
                "app": "falcon-eye",
                "component": "camera",
                "camera-id": str(camera.id),
            },
        },
        "spec": {
            "type": "NodePort",
            "selector": {"camera-id": str(camera.id)},
            "ports": [
                {"port": 8081, "targetPort": 8081, "name": "stream"},
                {"port": 8080, "targetPort": 8080, "name": "control"},
            ],
        },
    }
    
    return service, service_name


async def create_camera_deployment(camera: Camera) -> dict:
    """Create K8s deployment and service for a camera"""
    deployment, deployment_name = generate_deployment(camera)
    service, service_name = generate_service(camera, deployment_name)
    
    try:
        # Create deployment
        apps_api.create_namespaced_deployment(
            namespace=settings.k8s_namespace,
            body=deployment,
        )
        logger.info(f"Created deployment: {deployment_name}")
        
        # Create service
        created_service = core_api.create_namespaced_service(
            namespace=settings.k8s_namespace,
            body=service,
        )
        
        # Extract NodePorts
        stream_port = None
        control_port = None
        for port in created_service.spec.ports:
            if port.name == "stream":
                stream_port = port.node_port
            elif port.name == "control":
                control_port = port.node_port
        
        logger.info(f"Created service: {service_name} (stream: {stream_port}, control: {control_port})")
        
        return {
            "deployment_name": deployment_name,
            "service_name": service_name,
            "stream_port": stream_port,
            "control_port": control_port,
        }
        
    except ApiException as e:
        logger.error(f"K8s API error: {e.reason}")
        raise Exception(f"Kubernetes error: {e.reason}")


async def delete_camera_deployment(deployment_name: str, service_name: str):
    """Delete K8s deployment and service"""
    try:
        apps_api.delete_namespaced_deployment(
            name=deployment_name,
            namespace=settings.k8s_namespace,
        )
        logger.info(f"Deleted deployment: {deployment_name}")
    except ApiException as e:
        if e.status != 404:
            logger.error(f"Error deleting deployment: {e.reason}")
    
    try:
        core_api.delete_namespaced_service(
            name=service_name,
            namespace=settings.k8s_namespace,
        )
        logger.info(f"Deleted service: {service_name}")
    except ApiException as e:
        if e.status != 404:
            logger.error(f"Error deleting service: {e.reason}")


async def get_deployment_status(deployment_name: str) -> Optional[dict]:
    """Get deployment status"""
    try:
        deployment = apps_api.read_namespaced_deployment_status(
            name=deployment_name,
            namespace=settings.k8s_namespace,
        )
        status = deployment.status
        return {
            "ready": (status.ready_replicas or 0) == (status.replicas or 0),
            "replicas": status.replicas or 0,
            "ready_replicas": status.ready_replicas or 0,
            "available_replicas": status.available_replicas or 0,
        }
    except ApiException as e:
        if e.status == 404:
            return None
        raise


class K8sService:
    """Kubernetes service wrapper for async operations"""
    
    async def get_nodes(self) -> list[dict]:
        """Get all cluster nodes"""
        try:
            nodes = core_api.list_node()
            result = []
            for node in nodes.items:
                # Get node IP
                internal_ip = None
                for addr in node.status.addresses:
                    if addr.type == "InternalIP":
                        internal_ip = addr.address
                        break
                
                # Get node status
                ready = False
                for condition in node.status.conditions:
                    if condition.type == "Ready":
                        ready = condition.status == "True"
                        break
                
                # Check for taints
                taints = []
                if node.spec.taints:
                    taints = [{"key": t.key, "value": t.value, "effect": t.effect} for t in node.spec.taints]
                
                result.append({
                    "name": node.metadata.name,
                    "ip": internal_ip,
                    "ready": ready,
                    "taints": taints,
                    "labels": node.metadata.labels or {},
                    "architecture": node.status.node_info.architecture if node.status.node_info else None,
                    "os": node.status.node_info.operating_system if node.status.node_info else None,
                })
            
            return result
        except ApiException as e:
            logger.error(f"Error listing nodes: {e.reason}")
            return []
    
    async def get_pods_by_label(self, label_selector: str) -> list[dict]:
        """Get pods by label selector"""
        try:
            pods = core_api.list_namespaced_pod(
                namespace=settings.k8s_namespace,
                label_selector=label_selector,
            )
            return [
                {
                    "name": pod.metadata.name,
                    "status": pod.status.phase,
                    "node": pod.spec.node_name,
                    "ip": pod.status.pod_ip,
                }
                for pod in pods.items
            ]
        except ApiException as e:
            logger.error(f"Error listing pods: {e.reason}")
            return []
