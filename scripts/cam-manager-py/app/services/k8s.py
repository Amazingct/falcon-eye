"""Kubernetes deployment management service"""
import os
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
batch_api = client.BatchV1Api()


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
        
        tolerations = settings.get_node_tolerations(camera_node)
        if tolerations:
            deployment["spec"]["template"]["spec"]["tolerations"] = tolerations
    
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
                        "imagePullPolicy": "IfNotPresent",
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
                            {"name": "RECORDING_CHUNK_MINUTES", "value": os.getenv("RECORDING_CHUNK_MINUTES", "15")},
                            {"name": "INTERNAL_API_KEY", "value": os.getenv("INTERNAL_API_KEY", "")},
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
        # Auto-detect tolerations from node taints
        tolerations = settings.get_node_tolerations(recorder_node)
        if tolerations:
            deployment["spec"]["template"]["spec"]["tolerations"] = tolerations
    
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
            "type": "ClusterIP",
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
        
        # Create or reuse service (ClusterIP — internal only)
        try:
            core_api.create_namespaced_service(
                namespace=settings.k8s_namespace,
                body=service,
            )
            logger.info(f"Created service: {service_name}")
        except ApiException as e:
            if e.status == 409:
                logger.info(f"Service {service_name} already exists")
            else:
                raise
        
        return {
            "deployment_name": deployment_name,
            "service_name": service_name,
            "stream_port": 8081,
            "control_port": 8080,
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


async def create_agent_deployment(agent) -> dict:
    """Create K8s Deployment + Service for an agent pod"""
    import re
    name_slug = re.sub(r"[^a-z0-9-]", "-", agent.slug.lower()).strip("-")[:40]
    deployment_name = f"agent-{name_slug}"
    service_name = f"svc-agent-{name_slug}"

    # Resolve the LLM API key: per-agent override, or shared key from ConfigMap env
    resolved_key = agent.api_key_ref or ""
    if not resolved_key:
        if agent.provider == "anthropic":
            resolved_key = os.environ.get("ANTHROPIC_API_KEY", "")
        elif agent.provider == "openai":
            resolved_key = os.environ.get("OPENAI_API_KEY", "")

    env_vars = [
        {"name": "AGENT_ID", "value": str(agent.id)},
        {"name": "API_URL", "value": f"http://falcon-eye-api.{settings.k8s_namespace}.svc.cluster.local:8000"},
        {"name": "CHANNEL_TYPE", "value": agent.channel_type or ""},
        {"name": "LLM_PROVIDER", "value": agent.provider},
        {"name": "LLM_MODEL", "value": agent.model},
        {"name": "LLM_API_KEY", "value": resolved_key},
        {"name": "LLM_BASE_URL", "value": ""},
        {"name": "SYSTEM_PROMPT", "value": agent.system_prompt or ""},
    ]

    # Add channel-specific env vars
    channel_config = agent.channel_config or {}
    if agent.channel_type == "telegram" and channel_config.get("bot_token"):
        env_vars.append({"name": "TELEGRAM_BOT_TOKEN", "value": channel_config["bot_token"]})

    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": deployment_name,
            "namespace": settings.k8s_namespace,
            "labels": {
                "app": "falcon-eye",
                "component": "agent",
                "agent-id": str(agent.id),
            },
        },
        "spec": {
            "replicas": 1,
            "selector": {
                "matchLabels": {"agent-id": str(agent.id)},
            },
            "template": {
                "metadata": {
                    "labels": {
                        "app": "falcon-eye",
                        "component": "agent",
                        "agent-id": str(agent.id),
                    },
                },
                "spec": {
                    "containers": [{
                        "name": "agent",
                        "image": "ghcr.io/amazingct/falcon-eye-agent:latest",
                        "imagePullPolicy": os.environ.get("IMAGE_PULL_POLICY", "Always"),
                        "ports": [{"containerPort": 8080, "name": "http"}],
                        "envFrom": [{"configMapRef": {"name": "falcon-eye-config"}}],
                        "env": env_vars,
                        "resources": {
                            "requests": {"memory": "64Mi", "cpu": "50m"},
                            "limits": {
                                "memory": agent.memory_limit or "512Mi",
                                "cpu": agent.cpu_limit or "500m",
                            },
                        },
                    }],
                },
            },
        },
    }

    # Add node selector if specified
    if agent.node_name:
        deployment["spec"]["template"]["spec"]["nodeSelector"] = {
            "kubernetes.io/hostname": agent.node_name,
        }
        tolerations = settings.get_node_tolerations(agent.node_name)
        if tolerations:
            deployment["spec"]["template"]["spec"]["tolerations"] = tolerations

    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": service_name,
            "namespace": settings.k8s_namespace,
            "labels": {
                "app": "falcon-eye",
                "component": "agent",
                "agent-id": str(agent.id),
            },
        },
        "spec": {
            "type": "ClusterIP",
            "selector": {"agent-id": str(agent.id)},
            "ports": [{"port": 8080, "targetPort": 8080, "name": "http"}],
        },
    }

    try:
        try:
            apps_api.create_namespaced_deployment(namespace=settings.k8s_namespace, body=deployment)
            logger.info(f"Created agent deployment: {deployment_name}")
        except ApiException as e:
            if e.status == 409:
                apps_api.replace_namespaced_deployment(name=deployment_name, namespace=settings.k8s_namespace, body=deployment)
                logger.info(f"Replaced agent deployment: {deployment_name}")
            else:
                raise

        try:
            core_api.create_namespaced_service(namespace=settings.k8s_namespace, body=service)
            logger.info(f"Created agent service: {service_name}")
        except ApiException as e:
            if e.status != 409:
                raise
            logger.info(f"Agent service {service_name} already exists")

        return {"deployment_name": deployment_name, "service_name": service_name}
    except ApiException as e:
        logger.error(f"K8s API error creating agent deployment: {e.reason}")
        raise Exception(f"Kubernetes error: {e.reason}")


async def delete_agent_deployment(deployment_name: str, service_name: str = None):
    """Delete agent deployment + service"""
    try:
        apps_api.delete_namespaced_deployment(name=deployment_name, namespace=settings.k8s_namespace)
        logger.info(f"Deleted agent deployment: {deployment_name}")
    except ApiException as e:
        if e.status != 404:
            logger.error(f"Error deleting agent deployment: {e.reason}")

    if service_name:
        try:
            core_api.delete_namespaced_service(name=service_name, namespace=settings.k8s_namespace)
            logger.info(f"Deleted agent service: {service_name}")
        except ApiException as e:
            if e.status != 404:
                logger.error(f"Error deleting agent service: {e.reason}")


async def create_agent_job(agent, task: str,
                           caller_agent_id: str = None,
                           caller_session_id: str = None) -> dict:
    """Create a K8s Job for an ephemeral agent task (run-to-completion, no restart)."""
    import re
    name_slug = re.sub(r"[^a-z0-9-]", "-", agent.slug.lower()).strip("-")[:30]
    short_id = str(agent.id)[:8]
    job_name = f"agent-task-{name_slug}-{short_id}"

    resolved_key = agent.api_key_ref or ""
    if not resolved_key:
        if agent.provider == "anthropic":
            resolved_key = os.environ.get("ANTHROPIC_API_KEY", "")
        elif agent.provider == "openai":
            resolved_key = os.environ.get("OPENAI_API_KEY", "")

    env_vars = [
        {"name": "AGENT_ID", "value": str(agent.id)},
        {"name": "AGENT_TASK", "value": task},
        {"name": "CALLER_AGENT_ID", "value": caller_agent_id or ""},
        {"name": "CALLER_SESSION_ID", "value": caller_session_id or ""},
        {"name": "API_URL", "value": f"http://falcon-eye-api.{settings.k8s_namespace}.svc.cluster.local:8000"},
        {"name": "LLM_PROVIDER", "value": agent.provider},
        {"name": "LLM_MODEL", "value": agent.model},
        {"name": "LLM_API_KEY", "value": resolved_key},
        {"name": "LLM_BASE_URL", "value": ""},
        {"name": "SYSTEM_PROMPT", "value": agent.system_prompt or ""},
    ]

    job = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name,
            "namespace": settings.k8s_namespace,
            "labels": {
                "app": "falcon-eye",
                "component": "agent-task",
                "agent-id": str(agent.id),
            },
        },
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 600,
            "ttlSecondsAfterFinished": 300,
            "template": {
                "metadata": {
                    "labels": {
                        "app": "falcon-eye",
                        "component": "agent-task",
                        "agent-id": str(agent.id),
                    },
                },
                "spec": {
                    "restartPolicy": "Never",
                    "containers": [{
                        "name": "agent",
                        "image": "ghcr.io/amazingct/falcon-eye-agent:latest",
                        "imagePullPolicy": os.environ.get("IMAGE_PULL_POLICY", "Always"),
                        "envFrom": [{"configMapRef": {"name": "falcon-eye-config"}}],
                        "env": env_vars,
                        "resources": {
                            "requests": {"memory": "64Mi", "cpu": "50m"},
                            "limits": {
                                "memory": agent.memory_limit or "512Mi",
                                "cpu": agent.cpu_limit or "500m",
                            },
                        },
                    }],
                },
            },
        },
    }

    if agent.node_name:
        job["spec"]["template"]["spec"]["nodeSelector"] = {
            "kubernetes.io/hostname": agent.node_name,
        }
        tolerations = settings.get_node_tolerations(agent.node_name)
        if tolerations:
            job["spec"]["template"]["spec"]["tolerations"] = tolerations

    try:
        batch_api.create_namespaced_job(namespace=settings.k8s_namespace, body=job)
        logger.info(f"Created agent task job: {job_name}")
        return {"job_name": job_name}
    except ApiException as e:
        if e.status == 409:
            try:
                batch_api.delete_namespaced_job(
                    name=job_name, namespace=settings.k8s_namespace,
                    propagation_policy="Background",
                )
            except Exception:
                pass
            import asyncio
            await asyncio.sleep(3)
            batch_api.create_namespaced_job(namespace=settings.k8s_namespace, body=job)
            logger.info(f"Re-created agent task job: {job_name}")
            return {"job_name": job_name}
        logger.error(f"K8s API error creating agent job: {e.reason}")
        raise Exception(f"Kubernetes error: {e.reason}")


async def delete_agent_job(job_name: str):
    """Delete an agent task Job and its pods."""
    try:
        batch_api.delete_namespaced_job(
            name=job_name, namespace=settings.k8s_namespace,
            propagation_policy="Background",
        )
        logger.info(f"Deleted agent job: {job_name}")
    except ApiException as e:
        if e.status != 404:
            logger.error(f"Error deleting agent job: {e.reason}")


async def create_k8s_cronjob(cron_job, agent) -> str:
    """Create K8s CronJob resource"""
    import re
    name_slug = re.sub(r"[^a-z0-9-]", "-", cron_job.name.lower()).strip("-")[:40]
    cronjob_name = f"cron-{name_slug}-{str(cron_job.id)[:8]}"

    k8s_cronjob = {
        "apiVersion": "batch/v1",
        "kind": "CronJob",
        "metadata": {
            "name": cronjob_name,
            "namespace": settings.k8s_namespace,
            "labels": {
                "app": "falcon-eye",
                "component": "cron",
                "cron-id": str(cron_job.id),
            },
        },
        "spec": {
            "schedule": cron_job.cron_expr,
            "suspend": not cron_job.enabled,
            "successfulJobsHistoryLimit": 3,
            "failedJobsHistoryLimit": 3,
            "jobTemplate": {
                "metadata": {
                    "labels": {
                        "app": "falcon-eye",
                        "component": "cron",
                        "cron-id": str(cron_job.id),
                    },
                },
                "spec": {
                    "backoffLimit": 1,
                    "activeDeadlineSeconds": cron_job.timeout_seconds + 30,
                    "template": {
                        "metadata": {
                            "labels": {
                                "app": "falcon-eye",
                                "component": "cron",
                                "cron-id": str(cron_job.id),
                            },
                        },
                        "spec": {
                            "containers": [{
                                "name": "cron-runner",
                                "image": "ghcr.io/amazingct/falcon-eye-cron-runner:latest",
                                "imagePullPolicy": "IfNotPresent",
                                "env": [
                                    {"name": "API_URL", "value": f"http://falcon-eye-api.{settings.k8s_namespace}.svc.cluster.local:8000"},
                                    {"name": "AGENT_ID", "value": str(agent.id)},
                                    {"name": "CRON_JOB_ID", "value": str(cron_job.id)},
                                    {"name": "PROMPT", "value": cron_job.prompt},
                                    {"name": "SESSION_ID", "value": cron_job.session_id or ""},
                                    {"name": "TIMEOUT_SECONDS", "value": str(cron_job.timeout_seconds)},
                                ],
                                "envFrom": [{"configMapRef": {"name": "falcon-eye-config"}}],
                                "resources": {
                                    "requests": {"memory": "64Mi", "cpu": "50m"},
                                    "limits": {"memory": "128Mi", "cpu": "200m"},
                                },
                            }],
                            "restartPolicy": "Never",
                        },
                    },
                },
            },
        },
    }

    try:
        batch_api.create_namespaced_cron_job(namespace=settings.k8s_namespace, body=k8s_cronjob)
        logger.info(f"Created K8s CronJob: {cronjob_name}")
        return cronjob_name
    except ApiException as e:
        if e.status == 409:
            batch_api.replace_namespaced_cron_job(name=cronjob_name, namespace=settings.k8s_namespace, body=k8s_cronjob)
            logger.info(f"Replaced K8s CronJob: {cronjob_name}")
            return cronjob_name
        logger.error(f"K8s API error creating CronJob: {e.reason}")
        raise Exception(f"Kubernetes error: {e.reason}")


async def update_k8s_cronjob(cron_job, agent) -> None:
    """Update K8s CronJob resource"""
    if not cron_job.cronjob_name:
        return
    # Simplest approach: delete and recreate
    try:
        await delete_k8s_cronjob(cron_job.cronjob_name)
    except Exception:
        pass
    new_name = await create_k8s_cronjob(cron_job, agent)
    cron_job.cronjob_name = new_name


async def delete_k8s_cronjob(cronjob_name: str) -> None:
    """Delete K8s CronJob resource"""
    try:
        batch_api.delete_namespaced_cron_job(name=cronjob_name, namespace=settings.k8s_namespace)
        logger.info(f"Deleted K8s CronJob: {cronjob_name}")
    except ApiException as e:
        if e.status != 404:
            logger.error(f"Error deleting CronJob: {e.reason}")
            raise


async def trigger_k8s_cronjob(cron_job, agent) -> str:
    """Create a one-off Job from CronJob template (manual trigger)"""
    import re
    from datetime import datetime
    name_slug = re.sub(r"[^a-z0-9-]", "-", cron_job.name.lower()).strip("-")[:30]
    timestamp = datetime.utcnow().strftime("%H%M%S")
    job_name = f"cron-run-{name_slug}-{timestamp}"

    job = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name,
            "namespace": settings.k8s_namespace,
            "labels": {
                "app": "falcon-eye",
                "component": "cron",
                "cron-id": str(cron_job.id),
                "manual-trigger": "true",
            },
        },
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": cron_job.timeout_seconds + 30,
            "template": {
                "metadata": {
                    "labels": {
                        "app": "falcon-eye",
                        "component": "cron",
                        "cron-id": str(cron_job.id),
                    },
                },
                "spec": {
                    "containers": [{
                        "name": "cron-runner",
                        "image": "ghcr.io/amazingct/falcon-eye-cron-runner:latest",
                        "imagePullPolicy": "IfNotPresent",
                        "env": [
                            {"name": "API_URL", "value": f"http://falcon-eye-api.{settings.k8s_namespace}.svc.cluster.local:8000"},
                            {"name": "AGENT_ID", "value": str(agent.id)},
                            {"name": "CRON_JOB_ID", "value": str(cron_job.id)},
                            {"name": "PROMPT", "value": cron_job.prompt},
                            {"name": "SESSION_ID", "value": cron_job.session_id or ""},
                            {"name": "TIMEOUT_SECONDS", "value": str(cron_job.timeout_seconds)},
                        ],
                        "resources": {
                            "requests": {"memory": "64Mi", "cpu": "50m"},
                            "limits": {"memory": "128Mi", "cpu": "200m"},
                        },
                    }],
                    "restartPolicy": "Never",
                },
            },
        },
    }

    try:
        batch_api.create_namespaced_job(namespace=settings.k8s_namespace, body=job)
        logger.info(f"Created manual trigger Job: {job_name}")
        return job_name
    except ApiException as e:
        logger.error(f"K8s API error creating Job: {e.reason}")
        raise Exception(f"Kubernetes error: {e.reason}")


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
