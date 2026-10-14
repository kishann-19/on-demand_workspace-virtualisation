import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "data")).resolve())
    origin: str = field(default_factory=lambda: os.getenv("APP_ORIGIN", "http://localhost:8000").rstrip("/"))
    secure_cookies: bool = field(
        default_factory=lambda: os.getenv("SECURE_COOKIES", "false").lower() == "true"
    )
    registration: bool = field(
        default_factory=lambda: os.getenv("ALLOW_REGISTRATION", "true").lower() == "true"
    )
    runtime_image: str = field(
        default_factory=lambda: os.getenv("WORKSPACE_IMAGE", "cloudlab-workspace:local")
    )
    docker_url: str = field(default_factory=lambda: os.getenv("DOCKER_HOST", "unix:///var/run/docker.sock"))
    idle_minutes: int = field(default_factory=lambda: int(os.getenv("IDLE_TIMEOUT_MINUTES", "30")))
    max_workspaces: int = field(default_factory=lambda: int(os.getenv("MAX_WORKSPACES_PER_USER", "5")))
    max_running: int = field(default_factory=lambda: int(os.getenv("MAX_RUNNING_PER_USER", "2")))
    max_host_running: int = field(default_factory=lambda: int(os.getenv("MAX_HOST_RUNNING", "10")))
    backup_bucket: str = field(default_factory=lambda: os.getenv("S3_BUCKET", ""))
    backup_endpoint: str | None = field(default_factory=lambda: os.getenv("S3_ENDPOINT_URL") or None)
    admin_email: str = field(default_factory=lambda: os.getenv("ADMIN_EMAIL", ""))
    admin_password: str = field(default_factory=lambda: os.getenv("ADMIN_PASSWORD", ""))

    def __post_init__(self):
        if min(self.idle_minutes, self.max_workspaces, self.max_running, self.max_host_running) < 1:
            raise ValueError("Resource limits and idle timeout must be positive")
