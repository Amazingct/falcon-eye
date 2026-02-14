"""
Orphan pod cleanup task
Removes camera pods that exist in K8s but not in database
"""
import asyncio
import os
import logging
from kubernetes import client, config
from kubernetes.client.rest import ApiException

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Config from environment
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://falcon:falcon-eye-2026@localhost:5432/falconeye")
K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "falcon-eye")


def load_k8s_config():
    """Load Kubernetes configuration"""
    try:
        config.load_incluster_config()
        logger.info("Loaded in-cluster K8s config")
    except config.ConfigException:
        config.load_kube_config()
        logger.info("Loaded local K8s config")


async def get_db_camera_ids() -> set[str]:
    """Get all camera IDs from database"""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy import text
    
    engine = create_async_engine(DATABASE_URL)
    async with AsyncSession(engine) as session:
        result = await session.execute(text("SELECT id::text FROM cameras"))
        ids = {row[0] for row in result.fetchall()}
    await engine.dispose()
    return ids


def get_k8s_camera_pods() -> list[dict]:
    """Get all camera pods from K8s"""
    load_k8s_config()
    core_api = client.CoreV1Api()
    
    try:
        pods = core_api.list_namespaced_pod(
            namespace=K8S_NAMESPACE,
            label_selector="component=camera"
        )
        return [
            {
                "name": pod.metadata.name,
                "camera_id": pod.metadata.labels.get("camera-id"),
                "deployment": pod.metadata.labels.get("app"),
            }
            for pod in pods.items
            if pod.metadata.labels.get("camera-id")
        ]
    except ApiException as e:
        logger.error(f"Error listing pods: {e}")
        return []


def delete_orphan_deployment(camera_id: str):
    """Delete deployment and service for orphan camera"""
    load_k8s_config()
    apps_api = client.AppsV1Api()
    core_api = client.CoreV1Api()
    
    # Find and delete deployment
    try:
        deployments = apps_api.list_namespaced_deployment(
            namespace=K8S_NAMESPACE,
            label_selector=f"camera-id={camera_id}"
        )
        for dep in deployments.items:
            logger.info(f"Deleting orphan deployment: {dep.metadata.name}")
            apps_api.delete_namespaced_deployment(
                name=dep.metadata.name,
                namespace=K8S_NAMESPACE
            )
    except ApiException as e:
        if e.status != 404:
            logger.error(f"Error deleting deployment: {e}")
    
    # Find and delete service
    try:
        services = core_api.list_namespaced_service(
            namespace=K8S_NAMESPACE,
            label_selector=f"camera-id={camera_id}"
        )
        for svc in services.items:
            logger.info(f"Deleting orphan service: {svc.metadata.name}")
            core_api.delete_namespaced_service(
                name=svc.metadata.name,
                namespace=K8S_NAMESPACE
            )
    except ApiException as e:
        if e.status != 404:
            logger.error(f"Error deleting service: {e}")


async def cleanup_orphans():
    """Main cleanup function"""
    logger.info("Starting orphan pod cleanup...")
    
    # Get camera IDs from database
    db_camera_ids = await get_db_camera_ids()
    logger.info(f"Found {len(db_camera_ids)} cameras in database")
    
    # Get camera pods from K8s
    k8s_pods = get_k8s_camera_pods()
    logger.info(f"Found {len(k8s_pods)} camera pods in K8s")
    
    # Find orphans (in K8s but not in DB)
    orphan_camera_ids = set()
    for pod in k8s_pods:
        if pod["camera_id"] and pod["camera_id"] not in db_camera_ids:
            orphan_camera_ids.add(pod["camera_id"])
    
    if not orphan_camera_ids:
        logger.info("No orphan pods found")
        return
    
    logger.info(f"Found {len(orphan_camera_ids)} orphan camera(s)")
    
    # Delete orphans
    for camera_id in orphan_camera_ids:
        logger.info(f"Cleaning up orphan camera: {camera_id}")
        delete_orphan_deployment(camera_id)
    
    logger.info("Cleanup complete")


def main():
    """Entry point"""
    asyncio.run(cleanup_orphans())


if __name__ == "__main__":
    main()
