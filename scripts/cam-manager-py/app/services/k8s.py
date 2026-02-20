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
    
    # Add node selector and tolerations
    # USB cameras MUST run on their specific node
    # Network cameras use default node if set, otherwise auto-assign
    camera_node = None
    if camera.protocol == "usb" and camera.node_name and camera.node_name != "LAN":
        camera_node = camera.node_name
    elif camera.protocol != "usb" and settings.default_camera_node:
        camera_node = settings.default_camera_node
    
    if camera_node:
        deployment["spec"]["template"]["spec"]["nodeSelector"] = {
            "kubernetes.io/hostname": camera_node,
        }
        
        if settings.is_jetson_node(camera_node):
            deployment["spec"]["template"]["spec"]["tolerations"] = [{
                "key": "dedicated",
                "operator": "Equal",
                "value": "jetson",
                "effect": "NoSchedule",
            }]
    
    return deployment, deployment_name


def generate_recorder_deployment(camera: Camera, stream_url: str) -> tuple[dict, str]:
    """Generate K8s deployment manifest for a camera recorder"""
    name_slug = camera.name.lower().replace(" ", "-").replace("_", "-")
    name_slug = "".join(c for c in name_slug if c.isalnum() or c == "-")
    deployment_name = f"rec-{name_slug}"
    
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": deployment_name,
            "namespace": settings.k8s_namespace,
            "labels": {
                "app": "falcon-eye",
                "component": "recorder",
                "recorder-for": str(camera.id),
            },
        },
        "spec": {
            "replicas": 1,
            "selector": {
                "matchLabels": {
                    "app": "falcon-eye",
                    "component": "recorder",
                    "recorder-for": str(camera.id),
                },
            },
            "template": {
                "metadata": {
                    "labels": {
                        "app": "falcon-eye",
                        "component": "recorder",
                        "recorder-for": str(camera.id),
                    },
                },
                "spec": {
                    "containers": [{
                        "name": "recorder",
                        "image": "ghcr.io/amazingct/falcon-eye-recorder:latest",
                        "imagePullPolicy": "Always",
                        "ports": [{"containerPort": 8080, "name": "http"}],
                        "env": [
                            {"name": "CAMERA_ID", "value": str(camera.id)},
                            {"name": "CAMERA_NAME", "value": camera.name},
                            {"name": "STREAM_URL", "value": stream_url},
                            {"name": "API_URL", "value": "http://falcon-eye-api:8000"},
                            {"name": "RECORDINGS_PATH", "value": "/recordings"},
                            {
                                "name": "NODE_NAME",
                                "valueFrom": {
                                    "fieldRef": {"fieldPath": "spec.nodeName"},
                                },
                            },
                        ],
                        "volumeMounts": [{
                            "name": "recordings",
                            "mountPath": "/recordings",
                        }],
                        "resources": {
                            "requests": {"memory": "64Mi", "cpu": "50m"},
                            "limits": {"memory": "256Mi", "cpu": "500m"},
                        },
                    }],
                    "volumes": [{
                        "name": "recordings",
                        "hostPath": {
                            "path": "/data/falcon-eye/recordings",
                            "type": "DirectoryOrCreate",
                        },
                    }],
                },
            },
        },
    }
    
    # Add nodeSelector for recorder if camera has node or default is set
    recorder_node = camera.node_name if camera.node_name and camera.node_name != "LAN" else settings.default_recorder_node
    if recorder_node:
        deployment["spec"]["template"]["spec"]["nodeSelector"] = {
            "kubernetes.io/hostname": recorder_node,
        }
        # Add toleration for Jetson nodes
        if settings.is_jetson_node(recorder_node):
            deployment["spec"]["template"]["spec"]["tolerations"] = [{
                "key": "dedicated",
                "value": "jetson",
                "effect": "NoSchedule",
            }]
    
    return deployment, deployment_name


def generate_recorder_service(camera: Camera, deployment_name: str) -> tuple[dict, str]:
    """Generate K8s service manifest for a recorder"""
    name_slug = camera.name.lower().replace(" ", "-").replace("_", "-")
    name_slug = "".join(c for c in name_slug if c.isalnum() or c == "-")
    service_name = f"svc-rec-{name_slug}"
    
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": service_name,
            "namespace": settings.k8s_namespace,
            "labels": {
                "app": "falcon-eye",
                "component": "recorder",
                "recorder-for": str(camera.id),
            },
        },
        "spec": {
            "type": "ClusterIP",  # Internal only, API talks to it
            "selector": {
                "app": "falcon-eye",
                "component": "recorder",
                "recorder-for": str(camera.id),
            },
            "ports": [
                {"port": 8080, "targetPort": 8080, "name": "http"},
            ],
        },
    }
    
    return service, service_name


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
    """Create K8s deployment and service for a camera (handles conflicts by replacing)"""
    deployment, deployment_name = generate_deployment(camera)
    service, service_name = generate_service(camera, deployment_name)
    
    try:
        # Try to create deployment, replace if exists
        try:
            apps_api.create_namespaced_deployment(
                namespace=settings.k8s_namespace,
                body=deployment,
            )
            logger.info(f"Created deployment: {deployment_name}")
        except ApiException as e:
            if e.status == 409:  # Conflict - already exists
                logger.info(f"Deployment {deployment_name} exists, replacing...")
                apps_api.replace_namespaced_deployment(
                    name=deployment_name,
                    namespace=settings.k8s_namespace,
                    body=deployment,
                )
                logger.info(f"Replaced deployment: {deployment_name}")
            else:
                raise
        
        # Try to create service, get existing if conflict
        stream_port = None
        control_port = None
        try:
            created_service = core_api.create_namespaced_service(
                namespace=settings.k8s_namespace,
                body=service,
            )
            # Extract NodePorts from newly created service
            for port in created_service.spec.ports:
                if port.name == "stream":
                    stream_port = port.node_port
                elif port.name == "control":
                    control_port = port.node_port
            logger.info(f"Created service: {service_name} (stream: {stream_port}, control: {control_port})")
        except ApiException as e:
            if e.status == 409:  # Service exists, read it
                logger.info(f"Service {service_name} exists, reading...")
                existing_service = core_api.read_namespaced_service(
                    name=service_name,
                    namespace=settings.k8s_namespace,
                )
                for port in existing_service.spec.ports:
                    if port.name == "stream":
                        stream_port = port.node_port
                    elif port.name == "control":
                        control_port = port.node_port
                logger.info(f"Using existing service: {service_name} (stream: {stream_port}, control: {control_port})")
            else:
                raise
        
        return {
            "deployment_name": deployment_name,
            "service_name": service_name,
            "stream_port": stream_port,
            "control_port": control_port,
        }
        
    except ApiException as e:
        logger.error(f"K8s API error: {e.reason}")
        raise Exception(f"Kubernetes error: {e.reason}")


async def create_recorder_deployment(camera: Camera, stream_port: int, node_ip: str = None) -> dict:
    """Create K8s deployment for camera recorder"""
    # Build stream URL based on camera protocol
    name_slug = camera.name.lower().replace(" ", "-").replace("_", "-")
    name_slug = "".join(c for c in name_slug if c.isalnum() or c == "-")
    
    # USB cameras use Motion which serves MJPEG at root
    # Network cameras (RTSP/ONVIF) - record directly from source URL for best quality
    if camera.protocol == "usb":
        # Motion MJPEG stream
        stream_url = f"http://svc-{name_slug}.{settings.k8s_namespace}.svc.cluster.local:8081/"
    elif camera.source_url:
        # Use direct source URL for network cameras (RTSP/ONVIF)
        stream_url = camera.source_url
    else:
        # Fallback to internal service
        stream_url = f"http://svc-{name_slug}.{settings.k8s_namespace}.svc.cluster.local:8081/"
    
    deployment, deployment_name = generate_recorder_deployment(camera, stream_url)
    service, service_name = generate_recorder_service(camera, deployment_name)
    
    try:
        # Create or replace deployment
        try:
            apps_api.create_namespaced_deployment(
                namespace=settings.k8s_namespace,
                body=deployment,
            )
            logger.info(f"Created recorder deployment: {deployment_name}")
        except ApiException as e:
            if e.status == 409:
                apps_api.replace_namespaced_deployment(
                    name=deployment_name,
                    namespace=settings.k8s_namespace,
                    body=deployment,
                )
                logger.info(f"Replaced recorder deployment: {deployment_name}")
            else:
                raise
        
        # Create or get service
        recorder_port = None
        try:
            created_service = core_api.create_namespaced_service(
                namespace=settings.k8s_namespace,
                body=service,
            )
            recorder_port = 8080
            logger.info(f"Created recorder service: {service_name}")
        except ApiException as e:
            if e.status == 409:
                recorder_port = 8080
                logger.info(f"Recorder service {service_name} already exists")
            else:
                raise
        
        return {
            "recorder_deployment_name": deployment_name,
            "recorder_service_name": service_name,
            "recorder_port": recorder_port,
        }
        
    except ApiException as e:
        logger.error(f"K8s API error creating recorder: {e.reason}")
        raise Exception(f"Kubernetes error: {e.reason}")


async def delete_recorder_deployment(camera_id: str):
    """Delete recorder deployment and service for a camera"""
    # Find and delete recorder deployment
    try:
        deployments = apps_api.list_namespaced_deployment(
            namespace=settings.k8s_namespace,
            label_selector=f"component=recorder,recorder-for={camera_id}",
        )
        for dep in deployments.items:
            apps_api.delete_namespaced_deployment(
                name=dep.metadata.name,
                namespace=settings.k8s_namespace,
            )
            logger.info(f"Deleted recorder deployment: {dep.metadata.name}")
    except ApiException as e:
        if e.status != 404:
            logger.error(f"Error deleting recorder deployment: {e.reason}")
    
    # Find and delete recorder service
    try:
        services = core_api.list_namespaced_service(
            namespace=settings.k8s_namespace,
            label_selector=f"component=recorder,recorder-for={camera_id}",
        )
        for svc in services.items:
            core_api.delete_namespaced_service(
                name=svc.metadata.name,
                namespace=settings.k8s_namespace,
            )
            logger.info(f"Deleted recorder service: {svc.metadata.name}")
    except ApiException as e:
        if e.status != 404:
            logger.error(f"Error deleting recorder service: {e.reason}")


async def cleanup_stale_recorder_resources(valid_camera_ids: list[str]):
    """Clean up recorder resources for cameras that no longer exist in DB"""
    cleaned = 0
    
    # Find all recorder deployments
    try:
        deployments = apps_api.list_namespaced_deployment(
            namespace=settings.k8s_namespace,
            label_selector="component=recorder",
        )
        for dep in deployments.items:
            labels = dep.metadata.labels or {}
            recorder_for = labels.get("recorder-for")
            if recorder_for and recorder_for not in valid_camera_ids:
                try:
                    apps_api.delete_namespaced_deployment(
                        name=dep.metadata.name,
                        namespace=settings.k8s_namespace,
                    )
                    logger.info(f"Cleaned up stale recorder deployment: {dep.metadata.name} (camera {recorder_for} not in DB)")
                    cleaned += 1
                except ApiException:
                    pass
    except ApiException as e:
        logger.error(f"Error listing recorder deployments: {e.reason}")
    
    # Find all recorder services
    try:
        services = core_api.list_namespaced_service(
            namespace=settings.k8s_namespace,
            label_selector="component=recorder",
        )
        for svc in services.items:
            labels = svc.metadata.labels or {}
            recorder_for = labels.get("recorder-for")
            if recorder_for and recorder_for not in valid_camera_ids:
                try:
                    core_api.delete_namespaced_service(
                        name=svc.metadata.name,
                        namespace=settings.k8s_namespace,
                    )
                    logger.info(f"Cleaned up stale recorder service: {svc.metadata.name} (camera {recorder_for} not in DB)")
                    cleaned += 1
                except ApiException:
                    pass
    except ApiException as e:
        logger.error(f"Error listing recorder services: {e.reason}")
    
    return cleaned


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


async def get_camera_pod_status(camera_id: str) -> str:
    """Get actual pod status for a camera, returns: running, creating, error, stopped"""
    try:
        pods = core_api.list_namespaced_pod(
            namespace=settings.k8s_namespace,
            label_selector=f"camera-id={camera_id}",
        )
        
        if not pods.items:
            return "stopped"
        
        pod = pods.items[0]
        phase = pod.status.phase
        
        # Check container statuses
        if pod.status.container_statuses:
            for cs in pod.status.container_statuses:
                if cs.state.running:
                    return "running"
                elif cs.state.waiting:
                    reason = cs.state.waiting.reason
                    if reason in ["CrashLoopBackOff", "ErrImagePull", "ImagePullBackOff"]:
                        return "error"
                    return "creating"
                elif cs.state.terminated:
                    return "error" if cs.state.terminated.exit_code != 0 else "stopped"
        
        # Fall back to pod phase
        if phase == "Running":
            return "running"
        elif phase == "Pending":
            return "creating"
        elif phase in ["Failed", "Unknown"]:
            return "error"
        else:
            return "stopped"
            
    except ApiException:
        return "error"


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
