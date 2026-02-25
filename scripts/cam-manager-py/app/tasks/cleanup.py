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
_raw_db_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://falcon:falcon-eye-2026@localhost:5432/falconeye")
# Ensure async driver is used
if _raw_db_url.startswith("postgresql://"):
    DATABASE_URL = _raw_db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    DATABASE_URL = _raw_db_url
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
    
    # Find and delete camera deployment
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
    
    # Find and delete camera service
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
    
    # Find and delete recorder deployment (uses recorder-for label)
    try:
        deployments = apps_api.list_namespaced_deployment(
            namespace=K8S_NAMESPACE,
            label_selector=f"recorder-for={camera_id}"
        )
        for dep in deployments.items:
            logger.info(f"Deleting orphan recorder deployment: {dep.metadata.name}")
            apps_api.delete_namespaced_deployment(
                name=dep.metadata.name,
                namespace=K8S_NAMESPACE
            )
    except ApiException as e:
        if e.status != 404:
            logger.error(f"Error deleting recorder deployment: {e}")
    
    # Find and delete recorder service
    try:
        services = core_api.list_namespaced_service(
            namespace=K8S_NAMESPACE,
            label_selector=f"recorder-for={camera_id}"
        )
        for svc in services.items:
            logger.info(f"Deleting orphan recorder service: {svc.metadata.name}")
            core_api.delete_namespaced_service(
                name=svc.metadata.name,
                namespace=K8S_NAMESPACE
            )
    except ApiException as e:
        if e.status != 404:
            logger.error(f"Error deleting recorder service: {e}")


def cleanup_all_stale_resources(db_camera_ids: set[str]):
    """Clean up ALL stale K8s resources not registered to any camera"""
    load_k8s_config()
    apps_api = client.AppsV1Api()
    core_api = client.CoreV1Api()
    
    # Clean up stale camera deployments
    try:
        deployments = apps_api.list_namespaced_deployment(
            namespace=K8S_NAMESPACE,
            label_selector="component=camera"
        )
        for dep in deployments.items:
            camera_id = dep.metadata.labels.get("camera-id")
            if camera_id and camera_id not in db_camera_ids:
                logger.info(f"Deleting stale camera deployment: {dep.metadata.name} (camera {camera_id})")
                apps_api.delete_namespaced_deployment(name=dep.metadata.name, namespace=K8S_NAMESPACE)
    except ApiException as e:
        logger.error(f"Error cleaning camera deployments: {e}")
    
    # Clean up stale camera services
    try:
        services = core_api.list_namespaced_service(
            namespace=K8S_NAMESPACE,
            label_selector="component=camera"
        )
        for svc in services.items:
            camera_id = svc.metadata.labels.get("camera-id")
            if camera_id and camera_id not in db_camera_ids:
                logger.info(f"Deleting stale camera service: {svc.metadata.name} (camera {camera_id})")
                core_api.delete_namespaced_service(name=svc.metadata.name, namespace=K8S_NAMESPACE)
    except ApiException as e:
        logger.error(f"Error cleaning camera services: {e}")
    
    # Clean up stale recorder deployments
    try:
        deployments = apps_api.list_namespaced_deployment(
            namespace=K8S_NAMESPACE,
            label_selector="component=recorder"
        )
        for dep in deployments.items:
            camera_id = dep.metadata.labels.get("recorder-for")
            if camera_id and camera_id not in db_camera_ids:
                logger.info(f"Deleting stale recorder deployment: {dep.metadata.name} (camera {camera_id})")
                apps_api.delete_namespaced_deployment(name=dep.metadata.name, namespace=K8S_NAMESPACE)
    except ApiException as e:
        logger.error(f"Error cleaning recorder deployments: {e}")
    
    # Clean up stale recorder services
    try:
        services = core_api.list_namespaced_service(
            namespace=K8S_NAMESPACE,
            label_selector="component=recorder"
        )
        for svc in services.items:
            camera_id = svc.metadata.labels.get("recorder-for")
            if camera_id and camera_id not in db_camera_ids:
                logger.info(f"Deleting stale recorder service: {svc.metadata.name} (camera {camera_id})")
                core_api.delete_namespaced_service(name=svc.metadata.name, namespace=K8S_NAMESPACE)
    except ApiException as e:
        logger.error(f"Error cleaning recorder services: {e}")


def get_running_recorder_camera_ids() -> set[str]:
    """Get camera IDs that have running recorder pods"""
    load_k8s_config()
    core_api = client.CoreV1Api()
    
    try:
        pods = core_api.list_namespaced_pod(
            namespace=K8S_NAMESPACE,
            label_selector="component=recorder"
        )
        running_ids = set()
        for pod in pods.items:
            if pod.status.phase == "Running":
                # Recorder uses "recorder-for" label
                camera_id = pod.metadata.labels.get("recorder-for")
                if camera_id:
                    running_ids.add(camera_id)
        return running_ids
    except ApiException as e:
        logger.error(f"Error listing recorder pods: {e}")
        return set()


async def fix_orphaned_recordings():
    """Fix recordings stuck in 'recording' status when recorder pod is gone"""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy import text
    from datetime import datetime
    
    logger.info("Checking for orphaned recordings...")
    
    # Get camera IDs with running recorders
    running_recorders = get_running_recorder_camera_ids()
    logger.info(f"Found {len(running_recorders)} running recorder pods")
    
    engine = create_async_engine(DATABASE_URL)
    async with AsyncSession(engine) as session:
        # Find recordings marked as 'RECORDING' (enum is uppercase)
        result = await session.execute(
            text("SELECT id, camera_id::text FROM recordings WHERE status = 'RECORDING'")
        )
        active_recordings = result.fetchall()
        
        fixed_count = 0
        for rec_id, camera_id in active_recordings:
            if camera_id not in running_recorders:
                # Recorder pod is gone, mark recording as stopped
                await session.execute(
                    text("""
                        UPDATE recordings 
                        SET status = 'STOPPED', 
                            end_time = :end_time,
                            error_message = 'Recording stopped: Recorder pod terminated'
                        WHERE id = :id
                    """),
                    {"id": rec_id, "end_time": datetime.utcnow()}
                )
                fixed_count += 1
                logger.info(f"Fixed orphaned recording {rec_id} for camera {camera_id}")
        
        if fixed_count > 0:
            await session.commit()
            logger.info(f"Fixed {fixed_count} orphaned recording(s)")
        else:
            logger.info("No orphaned recordings found")
    
    await engine.dispose()


async def cleanup_uploaded_local_files():
    """Delete local recording files that have been successfully uploaded to cloud.
    
    Uses the file-server DaemonSet to delete files on remote nodes since the
    cleanup job may not run on the same node as the recording.
    """
    import httpx
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy import text
    
    # Fetch setting from API (DB-backed), fallback to env
    try:
        import httpx as _httpx
        api_url = os.getenv("API_URL", "http://falcon-eye-api:8000")
        async with _httpx.AsyncClient() as _c:
            _resp = await _c.get(f"{api_url}/api/internal/settings/CLOUD_DELETE_LOCAL", timeout=5)
            cloud_delete = _resp.json().get("value", "true").lower() == "true" if _resp.status_code == 200 else os.getenv("CLOUD_DELETE_LOCAL", "true").lower() == "true"
    except Exception:
        cloud_delete = os.getenv("CLOUD_DELETE_LOCAL", "true").lower() == "true"
    if not cloud_delete:
        logger.info("CLOUD_DELETE_LOCAL is false, skipping local cleanup")
        return
    
    engine = create_async_engine(DATABASE_URL)
    async with AsyncSession(engine) as session:
        # Find recordings that have cloud_url AND still have a file_path
        result = await session.execute(
            text("""
                SELECT id, camera_id::text, file_path, file_name, node_name
                FROM recordings
                WHERE cloud_url IS NOT NULL
                  AND file_path IS NOT NULL AND file_path != ''
                  AND status = 'UPLOADED'
            """)
        )
        rows = result.fetchall()
        
        if not rows:
            logger.info("No uploaded recordings with local files to clean")
            await engine.dispose()
            return
        
        logger.info(f"Found {len(rows)} uploaded recording(s) with local files to clean")
        
        # Get file-server pods for remote deletion
        load_k8s_config()
        core_api = client.CoreV1Api()
        try:
            fs_pods = core_api.list_namespaced_pod(
                namespace=K8S_NAMESPACE,
                label_selector="app=falcon-eye,component=file-server",
            )
            # Map node -> pod IP
            node_pod_ips = {}
            for pod in fs_pods.items:
                if pod.status.pod_ip and pod.spec.node_name:
                    node_pod_ips[pod.spec.node_name] = pod.status.pod_ip
        except Exception as e:
            logger.error(f"Failed to list file-server pods: {e}")
            await engine.dispose()
            return
        
        deleted_count = 0
        for rec_id, camera_id, file_path, file_name, node_name in rows:
            # Try local delete first
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"Deleted local file: {file_path}")
                    deleted_count += 1
                    await session.execute(
                        text("UPDATE recordings SET file_path = '' WHERE id = :id"),
                        {"id": rec_id},
                    )
                    continue
                except Exception as e:
                    logger.warning(f"Failed to delete local file {file_path}: {e}")
            
            # File not on this node — try via recorder pod's DELETE endpoint
            if not camera_id or not file_name:
                continue
            
            # Find recorder pod for this camera
            found_and_deleted = False
            try:
                rec_pods = core_api.list_namespaced_pod(
                    namespace=K8S_NAMESPACE,
                    label_selector=f"app=falcon-eye,component=recorder,recorder-for={camera_id}",
                )
                for pod in rec_pods.items:
                    if not pod.status.pod_ip or pod.status.phase != "Running":
                        continue
                    pod_ip = pod.status.pod_ip
                    async with httpx.AsyncClient(timeout=15) as http:
                        url = f"http://{pod_ip}:8080/files/{camera_id}/{file_name}"
                        try:
                            del_res = await http.delete(url)
                            if del_res.status_code == 200:
                                logger.info(f"Deleted remote file via recorder: {camera_id}/{file_name}")
                                found_and_deleted = True
                                break
                            elif del_res.status_code == 404:
                                logger.info(f"File already gone on recorder: {camera_id}/{file_name}")
                                found_and_deleted = True
                                break
                        except Exception as e:
                            logger.warning(f"Failed to delete via recorder pod {pod_ip}: {e}")
            except Exception as e:
                logger.warning(f"Failed to find recorder pods for {camera_id}: {e}")
            
            if not found_and_deleted:
                # Recorder might be stopped — skip DB update, retry next cleanup cycle
                logger.warning(f"Could not delete {camera_id}/{file_name} — recorder not available, will retry")
                continue
            
            # Only clear file_path in DB after confirmed deletion
            await session.execute(
                text("UPDATE recordings SET file_path = '' WHERE id = :id"),
                {"id": rec_id},
            )
            deleted_count += 1
        
        if deleted_count > 0:
            await session.commit()
            logger.info(f"Cleaned up {deleted_count} recording file reference(s)")
    
    await engine.dispose()


async def cleanup_orphans():
    """Main cleanup function"""
    logger.info("=" * 50)
    logger.info("Starting cleanup task...")
    logger.info("=" * 50)
    
    # 1. Fix orphaned recordings first
    await fix_orphaned_recordings()
    
    # 2. Clean up local files for cloud-uploaded recordings
    await cleanup_uploaded_local_files()
    
    # 3. Get camera IDs from database
    db_camera_ids = await get_db_camera_ids()
    logger.info(f"Found {len(db_camera_ids)} cameras in database")
    
    # 4. Clean up ALL stale K8s resources (deployments + services for cameras + recorders)
    logger.info("Cleaning up stale K8s resources...")
    cleanup_all_stale_resources(db_camera_ids)
    
    logger.info("=" * 50)
    logger.info("Cleanup complete")
    logger.info("=" * 50)


def main():
    """Entry point"""
    asyncio.run(cleanup_orphans())


if __name__ == "__main__":
    main()
