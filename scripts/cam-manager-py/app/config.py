"""Falcon-Eye Camera Manager Configuration"""
from pydantic_settings import BaseSettings
from functools import lru_cache
import logging
import time

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Server
    app_name: str = "Falcon-Eye Camera Manager"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    
    # Database - prefer DATABASE_URL env var if set
    database_url_env: str | None = None  # Maps to DATABASE_URL
    db_host: str = "postgres"
    db_port: int = 5432
    db_user: str = "falcon"
    db_password: str = "falcon-eye-2026"
    db_name: str = "falconeye"
    
    @property
    def database_url(self) -> str:
        """Get async database URL (asyncpg)"""
        if self.database_url_env:
            # Convert postgresql:// to postgresql+asyncpg://
            url = self.database_url_env
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return url
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
    
    @property
    def sync_database_url(self) -> str:
        """Get sync database URL (psycopg2)"""
        if self.database_url_env:
            # Ensure it's plain postgresql:// for sync
            url = self.database_url_env
            if "+asyncpg" in url:
                url = url.replace("+asyncpg", "")
            return url
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
    
    # Kubernetes
    k8s_namespace: str = "falcon-eye"
    k8s_config_path: str | None = None
    k8s_api_server: str | None = None
    k8s_token: str | None = None
    
    # NodePort range
    stream_port_start: int = 30900
    stream_port_end: int = 30999
    
    # Camera defaults
    default_resolution: str = "640x480"
    default_framerate: int = 15
    default_camera_node: str = ""  # Default node for camera pods (empty = auto)
    default_recorder_node: str = ""  # Default node for recorder pods (empty = auto)
    creating_timeout_minutes: int = 15
    default_stream_quality: int = 70
    
    # Jetson/special nodes that need tolerations (comma-separated via env)
    jetson_nodes: list[str] = []
    
    # --- Auto-discovered node cache ---
    _node_ip_cache: dict[str, str] = {}
    _node_taint_cache: dict[str, list[dict]] = {}  # node_name -> list of taints
    _node_cache_time: float = 0
    _NODE_CACHE_TTL: float = 300  # Refresh every 5 minutes
    
    def _refresh_node_cache(self) -> None:
        """Auto-discover node IPs and taints from Kubernetes API"""
        now = time.time()
        if self._node_ip_cache and (now - self._node_cache_time) < self._NODE_CACHE_TTL:
            return  # Cache still valid
        
        try:
            from kubernetes import client, config
            try:
                config.load_incluster_config()
            except config.ConfigException:
                config.load_kube_config()
            
            v1 = client.CoreV1Api()
            nodes = v1.list_node()
            new_ip_cache = {}
            new_taint_cache = {}
            for node in nodes.items:
                name = node.metadata.name
                for addr in node.status.addresses:
                    if addr.type == "InternalIP":
                        new_ip_cache[name] = addr.address
                        break
                # Cache taints for toleration auto-detection
                if node.spec.taints:
                    new_taint_cache[name] = [
                        {"key": t.key, "value": t.value, "effect": t.effect}
                        for t in node.spec.taints
                        if t.key not in ("node.kubernetes.io/not-ready", "node.kubernetes.io/unreachable")
                    ]
            
            if new_ip_cache:
                self._node_ip_cache = new_ip_cache
                self._node_taint_cache = new_taint_cache
                self._node_cache_time = now
                logger.info(f"Auto-discovered node IPs: {new_ip_cache}")
                if new_taint_cache:
                    logger.info(f"Auto-discovered node taints: {new_taint_cache}")
        except Exception as e:
            logger.warning(f"Failed to auto-discover nodes: {e}")
            # Keep stale cache if available
    
    def get_node_ip(self, node_name: str) -> str:
        """Get IP address for a node (auto-discovered from K8s API)"""
        self._refresh_node_cache()
        
        if node_name in self._node_ip_cache:
            return self._node_ip_cache[node_name]
        
        # Fallback: return first known node IP or localhost
        if self._node_ip_cache:
            fallback = next(iter(self._node_ip_cache.values()))
            logger.warning(f"Node '{node_name}' not found, falling back to {fallback}")
            return fallback
        
        logger.warning(f"No node IPs discovered, returning 127.0.0.1 for '{node_name}'")
        return "127.0.0.1"
    
    @property
    def node_ips(self) -> dict[str, str]:
        """Get all discovered node name → IP mappings"""
        self._refresh_node_cache()
        return dict(self._node_ip_cache)
    
    def get_node_tolerations(self, node_name: str) -> list[dict]:
        """Get tolerations needed for scheduling on a specific node.
        Auto-detected from K8s node taints — no hardcoded node lists needed."""
        self._refresh_node_cache()
        taints = self._node_taint_cache.get(node_name, [])
        return [
            {
                "key": t["key"],
                "operator": "Equal",
                "value": t.get("value", ""),
                "effect": t["effect"],
            }
            for t in taints
        ]
    
    def is_jetson_node(self, node_name: str) -> bool:
        """Check if node requires special tolerations (Jetson, GPU, etc.).
        Auto-detected from node taints, or overridden via JETSON_NODES env."""
        if self.jetson_nodes:
            return node_name in self.jetson_nodes
        # Auto-detect: check if node has any taints
        self._refresh_node_cache()
        return node_name in self._node_taint_cache
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # Map DATABASE_URL env var to database_url_env field
        fields = {
            'database_url_env': {'env': 'DATABASE_URL'}
        }


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()
