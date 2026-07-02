"""Application settings loaded from environment variables."""

from typing import List
from pydantic import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://netdeploy:password@localhost:5432/netdeploy"

    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # Git
    GIT_REPO_PATH: str = "/app/config_repo"
    GIT_REMOTE_URL: str = ""

    # API
    LOG_LEVEL: str = "info"
    ALLOWED_ORIGINS: List[str] = ["*"]
    SECRET_KEY: str = "changeme-in-production"

    # SSH defaults
    SSH_USERNAME: str = "admin"
    SSH_PASSWORD: str = ""
    SSH_TIMEOUT: int = 30

    # Deployment
    CANARY_HEALTH_WAIT_SECONDS: int = 300  # 5 min
    DEPLOY_DRY_RUN: bool = False  # skip real SSH — for local/dev testing

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
