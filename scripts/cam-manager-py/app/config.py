"""Falcon-Eye Camera Manager Configuration"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Server
    app_name: str = "Falcon-Eye Camera Manager"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 3000
    
    # Database
    db_host: str = "postgres.ace-db.svc.cluster.local"
    db_port: int = 5432
    db_user: str = "admin"
    db_password: str = "amazingct"
    db_name: str = "homedb"
    
    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
    
    @property
    def sync_database_url(self) -> str:
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
    
    # Kubernetes
    k8s_namespace: str = "falcon-eye"
    k8s_config_path: str | None = None
    k8s_api_server: str | None = None
    k8s_token: str | None = None
    
    # Node IPs
    node_ip_ace: str = "192.168.1.142"
    node_ip_falcon: str = "192.168.1.176"
    node_ip_k3s1: str = "192.168.1.207"
    node_ip_k3s2: str = "192.168.1.138"
    
    # NodePort range
    stream_port_start: int = 30900
    stream_port_end: int = 30999
    
    # Camera defaults
    default_resolution: str = "640x480"
    default_framerate: int = 15
    default_stream_quality: int = 70
    
    # Jetson nodes (require tolerations)
    jetson_nodes: list[str] = ["ace", "falcon"]
    
    def get_node_ip(self, node_name: str) -> str:
        """Get IP address for a node"""
        node_ips = {
            "ace": self.node_ip_ace,
            "falcon": self.node_ip_falcon,
            "k3s-1": self.node_ip_k3s1,
            "k3s-2": self.node_ip_k3s2,
        }
        return node_ips.get(node_name, self.node_ip_k3s1)
    
    def is_jetson_node(self, node_name: str) -> bool:
        """Check if node is a Jetson device"""
        return node_name in self.jetson_nodes
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()
